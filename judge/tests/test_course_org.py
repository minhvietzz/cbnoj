"""Courses inside organizations, and giving a whole lesson (or some of its problems) to a class."""
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from judge.models import ClassAssignment, ClassMember, Classroom, Course, CourseLesson, CourseLessonProblem, \
    Notification, Quiz, QuizAttempt, RoleInClass
from judge.tests.test_class_features import ClassFeatureBase, make_profile
from judge.utils import classroom as stats


class CourseOrgBase(ClassFeatureBase):
    def setUp(self):
        super().setUp()
        self.org_admin = make_profile('co_admin')
        self.org.admins.add(self.org_admin)
        self.org_admin.organizations.add(self.org)
        self.member = make_profile('co_member')
        self.member.organizations.add(self.org)
        self.course = Course.objects.create(name='Python', slug='python', organization=self.org, is_public=False)
        self.lesson = CourseLesson.objects.create(course=self.course, title='Loops', order=1)
        for i, p in enumerate(self.problems, 1):
            CourseLessonProblem.objects.create(lesson=self.lesson, problem=p, order=i)
        self.quiz = Quiz.objects.create(title='Loops quiz', slug='loops-q', mode='practice', is_public=False,
                                        creator=self.teacher, lesson=self.lesson)


class CoursePermissionTest(CourseOrgBase):
    def test_members_open_the_course_and_admins_edit_it(self):
        self.assertTrue(self.course.is_accessible_by(self.member.user))
        self.assertFalse(self.course.is_editable_by(self.member.user))
        self.assertTrue(self.course.is_editable_by(self.org_admin.user))
        self.assertFalse(self.course.is_accessible_by(self.outsider.user))
        self.assertFalse(self.course.is_editable_by(self.outsider.user))

    def test_course_without_organization_is_unchanged(self):
        plain = Course.objects.create(name='Plain', slug='plain')
        self.assertFalse(plain.is_accessible_by(self.member.user))
        self.assertFalse(plain.is_editable_by(self.org_admin.user))

    def test_private_org_course_is_listed_only_for_members(self):
        self.login(self.member)
        self.assertContains(self.client.get(reverse('course_list') + '?tab=all'), 'Python')
        self.login(self.outsider)
        self.assertNotContains(self.client.get(reverse('course_list') + '?tab=all'), 'Python')
        self.assertEqual(self.client.get(reverse('course_detail', args=('python',))).status_code, 404)

    def test_org_courses_tab(self):
        self.login(self.member)
        response = self.client.get(reverse('organization_courses', args=('school',)))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Python')
        self.assertNotContains(response, 'admin/judge/course/add')
        self.login(self.outsider)
        self.assertNotContains(self.client.get(reverse('organization_courses', args=('school',))), 'Python')


class LessonAssignmentProgressTest(CourseOrgBase):
    def lesson_assignment(self):
        return ClassAssignment.objects.create(classroom=self.classroom, title='Loops', kind='lesson',
                                              lesson=self.lesson)

    def test_problems_and_quizzes_of_the_lesson_count_equally(self):
        a = self.lesson_assignment()
        self.solve(self.s1, self.problems[0], 100)
        self.solve(self.s1, self.problems[1], 50)
        QuizAttempt.objects.create(quiz=self.quiz, user=self.s1, finished=timezone.now(), seed=1, score=10,
                                   max_score=10)
        self.solve(self.s2, self.problems[0], 100)
        progress = stats.assignment_progress(a, stats.student_ids(self.classroom))
        self.assertAlmostEqual(progress[self.s1.id]['done'], 2 / 3)
        self.assertAlmostEqual(progress[self.s1.id]['score'], round(10 * 2.5 / 3, 2))
        self.assertAlmostEqual(progress[self.s2.id]['done'], 1 / 3)
        self.assertEqual(progress[self.s3.id], {'done': 0.0, 'score': 0.0})

    def test_problems_added_to_the_lesson_later_are_included(self):
        a = self.lesson_assignment()
        self.assertEqual(len(a.get_problems()), 2)
        extra = self.problems[0].__class__.objects.create(
            code='FC', name='C', description='x', group=self.problems[0].group, time_limit=1, memory_limit=65536,
            points=100, partial=True, is_public=True)
        CourseLessonProblem.objects.create(lesson=self.lesson, problem=extra, order=3)
        self.assertEqual([p.code for p in a.get_problems()], ['FA', 'FB', 'FC'])

    def test_empty_lesson_has_no_progress(self):
        empty = CourseLesson.objects.create(course=self.course, title='Empty', order=2)
        a = ClassAssignment.objects.create(classroom=self.classroom, title='E', kind='lesson', lesson=empty)
        self.assertEqual(stats.assignment_progress(a, [self.s1.id])[self.s1.id], {'done': 0.0, 'score': 0.0})

    def test_deleting_the_lesson_removes_its_assignment(self):
        self.lesson_assignment()
        self.lesson.delete()
        self.assertFalse(ClassAssignment.objects.exists())

    def test_todo_for_lists_the_lesson_with_a_link_to_it(self):
        self.lesson_assignment()
        rows = stats.todo_for(self.s1)
        self.assertEqual([r['assignment'].kind for r in rows], ['lesson'])
        self.login(self.s1)
        self.assertContains(self.client.get('/'), self.lesson.get_absolute_url())


class GiveFromClassPageTest(CourseOrgBase):
    def url(self):
        return reverse('class_assignments', args=('10a1',))

    def test_teacher_who_cannot_edit_the_course_needs_the_class_in_it(self):
        self.login(self.teacher)
        response = self.client.post(self.url(), {'title': 'L', 'kind': 'lesson', 'lesson': self.lesson.id})
        self.assertEqual(response.status_code, 200)   # lesson is not even offered: not in the course, not editable
        self.assertFalse(ClassAssignment.objects.exists())

    def test_class_already_in_the_course_can_receive_the_lesson(self):
        self.course.classes.add(self.classroom)
        self.login(self.teacher)
        response = self.client.post(self.url(), {'title': 'L', 'kind': 'lesson', 'lesson': self.lesson.id,
                                                 'due': '29/11/2026 23:59'})
        self.assertEqual(response.status_code, 302)
        a = ClassAssignment.objects.get()
        self.assertEqual((a.kind, a.lesson_id), ('lesson', self.lesson.id))
        self.assertEqual(Notification.objects.filter(recipient=self.s1).count(), 1)

    def test_course_editor_adds_the_class_to_the_course_by_giving_the_lesson(self):
        self.org_admin.class_roles.create(classroom=self.classroom, role=RoleInClass.TEACHER)
        self.login(self.org_admin)
        response = self.client.post(self.url(), {'title': 'L', 'kind': 'lesson', 'lesson': self.lesson.id})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.course.classes.filter(pk=self.classroom.pk).exists())
        self.assertTrue(self.course.is_accessible_by(self.s1.user))

    def test_lesson_kind_needs_a_lesson(self):
        self.course.classes.add(self.classroom)
        self.login(self.teacher)
        response = self.client.post(self.url(), {'title': 'L', 'kind': 'lesson'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ClassAssignment.objects.exists())

    def test_assignments_page_shows_the_lesson_assignment(self):
        self.course.classes.add(self.classroom)
        ClassAssignment.objects.create(classroom=self.classroom, title='Whole loops', kind='lesson',
                                       lesson=self.lesson)
        self.login(self.s1)
        response = self.client.get(self.url())
        self.assertContains(response, 'Whole loops')
        self.assertContains(response, 'Python')
        self.assertContains(response, 'FA')

    def test_prefill_from_the_course_page(self):
        self.course.classes.add(self.classroom)
        self.login(self.teacher)
        response = self.client.get(self.url() + '?lesson=%d' % self.lesson.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['form'].initial['kind'], 'lesson')


class GiveFromCourseTest(CourseOrgBase):
    def setUp(self):
        super().setUp()
        self.course.classes.add(self.classroom)
        self.assign_url = reverse('course_lesson_assign', args=('python', self.lesson.id))

    def test_lesson_page_offers_the_button_to_class_staff_only(self):
        self.login(self.teacher)
        page = self.client.get(self.lesson.get_absolute_url())
        self.assertContains(page, self.assign_url)
        self.assertContains(page, self.assign_url + '?problem=FA')
        self.login(self.s1)
        self.assertNotContains(self.client.get(self.lesson.get_absolute_url()), self.assign_url)

    def test_students_and_outsiders_cannot_open_the_form(self):
        self.login(self.s1)
        self.assertEqual(self.client.get(self.assign_url).status_code, 403)
        self.assertEqual(self.client.post(self.assign_url, {'classroom': self.classroom.id, 'scope': 'lesson',
                                                            'title': 'x'}).status_code, 403)
        self.login(self.outsider)
        self.assertEqual(self.client.get(self.assign_url).status_code, 404)
        self.assertFalse(ClassAssignment.objects.exists())

    def test_form_defaults_to_the_class_of_the_course_and_preselects_the_problem(self):
        self.login(self.teacher)
        response = self.client.get(self.assign_url + '?problem=FB')
        self.assertEqual(response.status_code, 200)
        initial = response.context['form'].initial
        self.assertEqual(initial['classroom'], self.classroom.id)
        self.assertEqual(initial['scope'], 'problems')
        self.assertEqual(initial['problems'], [self.problems[1].id])

    def test_give_the_whole_lesson(self):
        self.login(self.teacher)
        response = self.client.post(self.assign_url, {
            'classroom': self.classroom.id, 'scope': 'lesson', 'title': 'Loops', 'due': '29/11/2026 23:59'})
        self.assertEqual(response.status_code, 302)
        a = ClassAssignment.objects.get()
        self.assertEqual((a.kind, a.lesson_id, a.classroom_id), ('lesson', self.lesson.id, self.classroom.id))
        self.assertEqual(Notification.objects.filter(recipient=self.s1).count(), 1)

    def test_give_only_one_problem_of_the_lesson(self):
        self.login(self.teacher)
        response = self.client.post(self.assign_url, {
            'classroom': self.classroom.id, 'scope': 'problems', 'problems': [self.problems[1].id], 'title': 'B'})
        self.assertEqual(response.status_code, 302)
        a = ClassAssignment.objects.get()
        self.assertEqual(a.kind, 'problem')
        self.assertEqual([p.code for p in a.problems.all()], ['FB'])
        self.assertEqual(a.lesson_id, self.lesson.id)
        self.assertEqual([p.code for p in a.get_problems()], ['FB'])

    def test_problems_scope_needs_a_choice(self):
        self.login(self.teacher)
        response = self.client.post(self.assign_url, {'classroom': self.classroom.id, 'scope': 'problems',
                                                      'title': 'B'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ClassAssignment.objects.exists())

    def test_problem_of_another_lesson_cannot_be_smuggled_in(self):
        other = CourseLesson.objects.create(course=self.course, title='Other', order=2)
        extra = self.problems[0].__class__.objects.create(
            code='FZ', name='Z', description='x', group=self.problems[0].group, time_limit=1, memory_limit=65536,
            points=100, partial=True, is_public=True)
        CourseLessonProblem.objects.create(lesson=other, problem=extra, order=1)
        self.login(self.teacher)
        response = self.client.post(self.assign_url, {'classroom': self.classroom.id, 'scope': 'problems',
                                                      'problems': [extra.id], 'title': 'Z'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ClassAssignment.objects.exists())

    def test_only_own_classes_are_offered(self):
        other = Classroom.objects.create(name='11B', slug='11b', organization=self.org)
        self.login(self.teacher)
        response = self.client.post(self.assign_url, {'classroom': other.id, 'scope': 'lesson', 'title': 'x'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ClassAssignment.objects.exists())

    def test_whole_lesson_for_a_class_outside_the_course_needs_course_edit_rights(self):
        other = Classroom.objects.create(name='11B', slug='11b', organization=self.org)
        ClassMember.objects.create(classroom=other, user=self.teacher, role=RoleInClass.TEACHER)
        self.login(self.teacher)
        response = self.client.post(self.assign_url, {'classroom': other.id, 'scope': 'lesson', 'title': 'x'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ClassAssignment.objects.exists())
        self.assertFalse(self.course.classes.filter(pk=other.pk).exists())
        # one problem does not need the class to be in the course
        response = self.client.post(self.assign_url, {'classroom': other.id, 'scope': 'problems',
                                                      'problems': [self.problems[0].id], 'title': 'x'})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.course.classes.filter(pk=other.pk).exists())

    def test_hidden_lesson_is_not_assignable_by_non_editors(self):
        CourseLesson.objects.filter(pk=self.lesson.pk).update(is_visible=False)
        self.login(self.teacher)
        self.assertEqual(self.client.get(self.assign_url).status_code, 404)

    def test_anonymous_is_sent_to_login(self):
        self.assertEqual(self.client.get(self.assign_url).status_code, 302)

    def test_due_dates_are_optional_and_remind_logic_still_works(self):
        self.login(self.teacher)
        self.client.post(self.assign_url, {'classroom': self.classroom.id, 'scope': 'lesson', 'title': 'Loops',
                                           'due': (timezone.now() + timedelta(hours=5)).strftime('%d/%m/%Y %H:%M')})
        from judge.tasks.classroom import remind_due_assignments
        remind_due_assignments()
        self.assertEqual(Notification.objects.filter(recipient=self.s1).count(), 2)   # new + reminder
