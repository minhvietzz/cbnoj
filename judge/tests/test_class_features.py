from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from judge.models import ClassAnnouncement, ClassAssignment, ClassMember, Classroom, Course, Language, Notification, \
    Organization, Problem, ProblemGroup, ProblemType, Profile, Quiz, QuizAttempt, RoleInClass, Submission
from judge.tasks.classroom import remind_due_assignments
from judge.utils import classroom as stats


def make_profile(username, **extra):
    user = get_user_model().objects.create_user(username, password='x', email=username + '@example.com', **extra)
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile


class ClassFeatureBase(TestCase):
    def setUp(self):
        cache.clear()
        self.org = Organization.objects.create(name='School', slug='school', short_name='SC', about='x')
        self.teacher = make_profile('feat_teacher')
        self.s1 = make_profile('feat_s1')
        self.s2 = make_profile('feat_s2')
        self.s3 = make_profile('feat_s3')
        self.outsider = make_profile('feat_outsider')
        self.classroom = Classroom.objects.create(name='10A1', slug='10a1', organization=self.org)
        ClassMember.objects.create(classroom=self.classroom, user=self.teacher, role=RoleInClass.HOMEROOM)
        for s in (self.s1, self.s2, self.s3):
            ClassMember.objects.create(classroom=self.classroom, user=s, role=RoleInClass.STUDENT)
        group = ProblemGroup.objects.create(name='g', full_name='G')
        ptype = ProblemType.objects.create(name='t', full_name='T')
        self.language = Language.objects.create(key='PYF', name='Python', short_name='PYF', common_name='Python',
                                                ace='python', pygments='python', extension='py')
        self.problems = []
        for code in ('FA', 'FB'):
            p = Problem.objects.create(code=code, name='Problem ' + code, description='x', group=group, time_limit=1,
                                       memory_limit=65536, points=100, partial=True, is_public=True)
            p.types.set([ptype])
            self.problems.append(p)

    def solve(self, profile, problem, points, when=None):
        sub = Submission.objects.create(user=profile, problem=problem, language=self.language, status='D',
                                        result='AC' if points >= problem.points else 'WA', points=points)
        if when is not None:
            Submission.objects.filter(pk=sub.pk).update(date=when)
        return sub

    def assignment(self, **extra):
        a = ClassAssignment.objects.create(classroom=self.classroom, title='Arrays', kind='problem', **extra)
        a.problems.set(self.problems)
        return a

    def login(self, profile):
        self.client.force_login(profile.user)


class AssignmentProgressTest(ClassFeatureBase):
    def test_problem_assignment_progress(self):
        a = self.assignment()
        self.solve(self.s1, self.problems[0], 100)
        self.solve(self.s1, self.problems[1], 100)
        self.solve(self.s2, self.problems[0], 50)
        progress = stats.assignment_progress(a, stats.student_ids(self.classroom))
        self.assertEqual(progress[self.s1.id], {'done': 1.0, 'score': 10.0})
        self.assertEqual(progress[self.s2.id], {'done': 0.0, 'score': 2.5})
        self.assertEqual(progress[self.s3.id], {'done': 0.0, 'score': 0.0})

    def test_quiz_assignment_progress_uses_best_finished_attempt(self):
        quiz = Quiz.objects.create(title='Q', slug='q', mode='practice', is_public=True, creator=self.teacher)
        a = ClassAssignment.objects.create(classroom=self.classroom, title='Quiz', kind='quiz', quiz=quiz)
        QuizAttempt.objects.create(quiz=quiz, user=self.s1, finished=timezone.now(), seed=1, score=4, max_score=10)
        QuizAttempt.objects.create(quiz=quiz, user=self.s1, finished=timezone.now(), seed=2, score=8, max_score=10)
        QuizAttempt.objects.create(quiz=quiz, user=self.s2, seed=3, score=10, max_score=10)   # not finished
        QuizAttempt.objects.create(quiz=quiz, user=self.s3, finished=timezone.now(), seed=4, score=10, max_score=10,
                                   invalidated=True)
        progress = stats.assignment_progress(a, stats.student_ids(self.classroom))
        self.assertEqual(progress[self.s1.id], {'done': 1.0, 'score': 8.0})
        self.assertEqual(progress[self.s2.id]['done'], 0.0)
        self.assertEqual(progress[self.s3.id]['done'], 0.0)

    def test_grade_book_blank_until_overdue(self):
        future = self.assignment(due=timezone.now() + timedelta(days=3))
        past = ClassAssignment.objects.create(classroom=self.classroom, title='Old', kind='problem',
                                              due=timezone.now() - timedelta(days=1))
        past.problems.set(self.problems[:1])
        self.solve(self.s1, self.problems[0], 100)
        book = stats.grade_book(self.classroom, [future, past], stats.student_ids(self.classroom))
        self.assertEqual(book[self.s1.id]['cells'], [5.0, 10.0])
        self.assertEqual(book[self.s3.id]['cells'], [None, 0.0], 'blank while open, zero once overdue')
        self.assertEqual(book[self.s3.id]['average'], 0.0)


class RankingTest(ClassFeatureBase):
    def test_ranking_orders_by_weighted_score_and_has_movement(self):
        now = timezone.now()
        for p, pts in ((self.s1, 100), (self.s2, 60)):
            self.solve(p, self.problems[0], pts, when=now - timedelta(hours=1))
        rows, weights, _start = stats.ranking(self.classroom, 'year', now=now)
        order = [r['profile_id'] for r in rows]
        self.assertEqual(order[:2], [self.s1.id, self.s2.id])
        self.assertEqual(rows[0]['rank'], 1)
        self.assertGreater(rows[0]['total'], rows[1]['total'])
        self.assertEqual(sum(weights.values()), 100)
        self.assertEqual(len(rows), 3)

    def test_ties_share_a_rank(self):
        rows, _w, _s = stats.ranking(self.classroom, 'week')
        self.assertEqual({r['rank'] for r in rows}, {1}, 'nobody has activity: everyone is first')

    def test_period_start_is_monday_for_week(self):
        start = stats.period_start('week')
        self.assertEqual(start.weekday(), 0)
        self.assertEqual((start.hour, start.minute), (0, 0))

    def test_inactive_students_listed_for_teachers(self):
        self.solve(self.s1, self.problems[0], 100)
        names = {w['profile'].user.username for w in stats.inactive_students(self.classroom)}
        self.assertEqual(names, {'feat_s2', 'feat_s3'})

    def test_heat_grid_shape(self):
        counts = stats.activity_by_day(stats.student_ids(self.classroom))
        self.assertEqual(len(stats.heat_levels(counts)), 12 * 7)


class ClassPagesTest(ClassFeatureBase):
    def test_all_tabs_render_for_teacher_and_student(self):
        self.assignment(due=timezone.now() + timedelta(days=2))
        self.solve(self.s1, self.problems[0], 100)
        for who in (self.teacher, self.s1):
            self.login(who)
            for name in ('class_detail', 'class_assignments', 'class_ranking', 'class_grades', 'class_members',
                         'class_exams'):
                response = self.client.get(reverse(name, args=('10a1',)))
                self.assertEqual(response.status_code, 200, '%s for %s' % (name, who))
        self.assertContains(self.client.get(reverse('class_ranking', args=('10a1',)) + '?period=month'), 'feat_s1')

    def test_outsider_sees_nothing(self):
        self.login(self.outsider)
        for name in ('class_detail', 'class_assignments', 'class_ranking', 'class_grades', 'class_exams'):
            self.assertEqual(self.client.get(reverse(name, args=('10a1',))).status_code, 404)

    def test_teacher_creates_problem_assignment_and_students_are_notified(self):
        self.login(self.teacher)
        response = self.client.post(reverse('class_assignments', args=('10a1',)), {
            'title': 'Arrays', 'kind': 'problem', 'problem_codes': 'FA, FB', 'due': '29/11/2026 23:59',
            'description': 'Do it'})
        self.assertEqual(response.status_code, 302)
        a = ClassAssignment.objects.get(title='Arrays')
        self.assertEqual(sorted(a.problems.values_list('code', flat=True)), ['FA', 'FB'])
        self.assertIsNotNone(a.due)
        self.assertEqual(Notification.objects.filter(recipient=self.s1).count(), 1)
        self.assertEqual(Notification.objects.filter(recipient=self.teacher).count(), 0)

    def test_assignment_validation_and_permissions(self):
        self.login(self.teacher)
        url = reverse('class_assignments', args=('10a1',))
        bad = self.client.post(url, {'title': 'x', 'kind': 'problem', 'problem_codes': 'NOPE'})
        self.assertEqual(bad.status_code, 200)
        self.assertContains(bad, 'NOPE')
        self.assertFalse(ClassAssignment.objects.exists())
        no_quiz = self.client.post(url, {'title': 'x', 'kind': 'quiz'})
        self.assertEqual(no_quiz.status_code, 200)
        self.login(self.s1)
        self.assertEqual(self.client.post(url, {'title': 'x', 'kind': 'problem', 'problem_codes': 'FA'}).status_code,
                         403)

    def test_hidden_future_assignments_are_not_shown_to_students(self):
        self.assignment(opens=timezone.now() + timedelta(days=5))
        self.login(self.s1)
        self.assertNotContains(self.client.get(reverse('class_assignments', args=('10a1',))), 'Arrays')
        self.login(self.teacher)
        self.assertContains(self.client.get(reverse('class_assignments', args=('10a1',))), 'Arrays')

    def test_announcements(self):
        self.login(self.teacher)
        self.client.post(reverse('class_announce', args=('10a1',)), {'text': 'Exam on Friday', 'pinned': 'on'})
        note = ClassAnnouncement.objects.get()
        self.assertTrue(note.pinned)
        self.assertContains(self.client.get(self.classroom.get_absolute_url()), 'Exam on Friday')
        self.assertEqual(Notification.objects.filter(recipient=self.s2).count(), 1)
        self.login(self.s1)
        self.assertEqual(self.client.post(reverse('class_announce', args=('10a1',)), {'text': 'hack'}).status_code, 403)
        self.login(self.teacher)
        self.client.post(reverse('class_announce', args=('10a1',)), {'action': 'delete', 'announcement': note.id})
        self.assertFalse(ClassAnnouncement.objects.exists())

    def test_assignment_delete(self):
        a = self.assignment()
        self.login(self.s1)
        self.assertEqual(self.client.post(reverse('class_assignment_delete', args=('10a1',)),
                                          {'assignment': a.id}).status_code, 403)
        self.login(self.teacher)
        self.client.post(reverse('class_assignment_delete', args=('10a1',)), {'assignment': a.id})
        self.assertFalse(ClassAssignment.objects.exists())

    def test_grade_export_is_for_staff_only(self):
        self.assignment()
        self.login(self.teacher)
        csv_response = self.client.get(reverse('class_grades', args=('10a1',)) + '?export=csv')
        self.assertEqual(csv_response.status_code, 200)
        self.assertIn('feat_s1', csv_response.content.decode('utf-8'))
        xlsx_response = self.client.get(reverse('class_grades', args=('10a1',)) + '?export=xlsx')
        self.assertEqual(xlsx_response.status_code, 200)
        self.login(self.s1)
        self.assertEqual(self.client.get(reverse('class_grades', args=('10a1',)) + '?export=csv').status_code, 403)

    def test_student_grade_page_shows_only_own_row(self):
        self.assignment()
        self.login(self.s1)
        page = self.client.get(reverse('class_grades', args=('10a1',))).content.decode('utf-8')
        self.assertIn('feat_s1', page)
        self.assertNotIn('feat_s2', page)

    def test_my_classes_shows_deadline_counts(self):
        self.assignment(due=timezone.now() + timedelta(days=2))
        self.login(self.s1)
        response = self.client.get(reverse('class_list'))
        self.assertEqual(response.context['classes'][0].due_count, 1)
        self.assertEqual(response.context['classes'][0].badge, '10A')


class ReminderTest(ClassFeatureBase):
    def test_reminder_goes_once_to_unfinished_students(self):
        a = self.assignment(due=timezone.now() + timedelta(hours=10))
        self.solve(self.s1, self.problems[0], 100)
        self.solve(self.s1, self.problems[1], 100)
        remind_due_assignments()
        self.assertEqual(Notification.objects.filter(recipient=self.s1).count(), 0, 'finished: not reminded')
        self.assertEqual(Notification.objects.filter(recipient=self.s2).count(), 1)
        remind_due_assignments()
        self.assertEqual(Notification.objects.filter(recipient=self.s2).count(), 1, 'only once')
        a.refresh_from_db()
        self.assertTrue(a.reminded)

    def test_far_or_past_deadlines_are_not_reminded(self):
        self.assignment(due=timezone.now() + timedelta(days=3))
        self.assignment(due=timezone.now() - timedelta(hours=1))
        remind_due_assignments()
        self.assertEqual(Notification.objects.count(), 0)


class ClassAccessTest(ClassFeatureBase):
    def test_class_members_can_take_a_class_quiz(self):
        quiz = Quiz.objects.create(title='Private', slug='private-q', mode='practice', is_public=False,
                                   creator=self.teacher)
        self.assertFalse(quiz.is_accessible_by(self.s1.user))
        quiz.classes.add(self.classroom)
        self.assertTrue(quiz.is_accessible_by(self.s1.user))
        self.assertFalse(quiz.is_accessible_by(self.outsider.user))

    def test_class_members_are_students_of_the_course(self):
        course = Course.objects.create(name='C', slug='c', is_public=False)
        self.assertFalse(course.is_accessible_by(self.s1.user))
        course.classes.add(self.classroom)
        self.assertTrue(course.is_accessible_by(self.s1.user))
        self.assertEqual(course.get_role(self.s1), 'ST')
        self.assertEqual({p.id for p in course.get_students()}, {self.s1.id, self.s2.id, self.s3.id})
        self.assertFalse(course.is_accessible_by(self.outsider.user))


class DashboardTest(ClassFeatureBase):
    def test_todo_lists_unfinished_assignments_soonest_first(self):
        late = self.assignment(due=timezone.now() + timedelta(days=5))
        soon = ClassAssignment.objects.create(classroom=self.classroom, title='Soon', kind='problem',
                                              due=timezone.now() + timedelta(days=1))
        soon.problems.set(self.problems[:1])
        rows = stats.todo_for(self.s1)
        self.assertEqual([r['assignment'].id for r in rows], [soon.id, late.id])
        self.assertFalse(rows[0]['started'])
        self.solve(self.s1, self.problems[0], 100)
        rows = stats.todo_for(self.s1)
        self.assertEqual([r['assignment'].id for r in rows], [late.id], 'finished work disappears')
        self.assertTrue(rows[0]['started'])
        self.assertEqual(stats.todo_for(self.outsider), [])
        self.assertEqual(stats.todo_for(self.teacher), [], 'only students have a to-do list')

    def test_todo_skips_overdue_and_not_yet_open(self):
        self.assignment(due=timezone.now() - timedelta(hours=1))
        self.assignment(opens=timezone.now() + timedelta(days=1))
        self.assertEqual(stats.todo_for(self.s1), [])

    def test_upcoming_exams_follow_access(self):
        quiz = Quiz.objects.create(title='Mid', slug='mid', mode='exam', is_public=False, creator=self.teacher,
                                   start_time=timezone.now() + timedelta(days=2),
                                   end_time=timezone.now() + timedelta(days=2, hours=1), time_limit=45)
        self.assertEqual(stats.upcoming_exams(self.s1.user), [])
        quiz.classes.add(self.classroom)
        items = stats.upcoming_exams(self.s1.user)
        self.assertEqual([i['name'] for i in items], ['Mid'])
        self.assertEqual(stats.upcoming_exams(self.outsider.user), [])

    def test_home_page_shows_the_dashboard_blocks(self):
        self.assignment(due=timezone.now() + timedelta(days=2))
        self.login(self.s1)
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['home_todo']), 1)


class OrganizationTabsTest(ClassFeatureBase):
    def setUp(self):
        super().setUp()
        self.member = self.s1
        self.member.organizations.add(self.org)
        self.org.admins.add(self.teacher)
        self.teacher.organizations.add(self.org)

    def test_exams_page_lists_contests_and_quizzes_of_the_organization(self):
        quiz = Quiz.objects.create(title='Org exam', slug='org-exam', mode='exam', creator=self.teacher,
                                   start_time=timezone.now() + timedelta(days=1),
                                   end_time=timezone.now() + timedelta(days=1, hours=1), time_limit=30)
        quiz.organizations.add(self.org)
        self.login(self.member)
        response = self.client.get(reverse('organization_exams', args=('school',)))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Org exam')

    def test_exams_page_needs_membership(self):
        self.login(self.outsider)
        response = self.client.get(reverse('organization_exams', args=('school',)))
        self.assertNotContains(response, 'Org exam')

    def test_classes_page_shows_own_classes_to_members_and_all_to_admins(self):
        other = Classroom.objects.create(name='11B', slug='11b', organization=self.org)
        self.login(self.member)
        page = self.client.get(reverse('organization_classes', args=('school',))).content.decode('utf-8')
        self.assertIn('10A1', page)
        self.assertNotIn('11B', page)
        self.login(self.teacher)
        page = self.client.get(reverse('organization_classes', args=('school',))).content.decode('utf-8')
        self.assertIn('11B', page)
        self.assertEqual(other.organization, self.org)


class ClassReportTest(ClassFeatureBase):
    def test_report_is_for_staff_and_has_the_numbers(self):
        a = self.assignment()
        self.solve(self.s1, self.problems[0], 100)
        self.solve(self.s1, self.problems[1], 100)
        self.login(self.teacher)
        url = reverse('class_report_print', args=('10a1',))
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['summary']['students'], 3)
        self.assertEqual(response.context['summary']['top'], 10.0)
        self.assertContains(response, 'feat_s1')
        sheets = self.client.get(url + '?students=1')
        self.assertContains(sheets, 'class="student"', count=3)
        self.assertEqual(a.classroom, self.classroom)
        self.login(self.s1)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.login(self.outsider)
        self.assertEqual(self.client.get(url).status_code, 404)
