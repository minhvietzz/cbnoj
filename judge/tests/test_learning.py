from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from judge.models import (Badge, ClassMember, Classroom, Course, CourseLesson, CourseLessonProblem, CourseRole,
                          Language, Organization, Problem, ProblemGroup, ProblemType, Profile, Quiz, QuizAttempt,
                          RoleInClass, Submission)
from judge.utils import learning


def make_profile(username):
    user = get_user_model().objects.create_user(username, password='x', email=username + '@example.com')
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile


class LearningBase(TestCase):
    def setUp(self):
        self.me = make_profile('lr_me')
        self.other = make_profile('lr_other')
        self.language = Language.objects.create(key='PYL', name='Python', short_name='PYL', common_name='Python',
                                                ace='python', pygments='python', extension='py')
        ptype = ProblemType.objects.create(name='lt', full_name='LT')
        self.arrays = ProblemGroup.objects.create(name='arr', full_name='Arrays')
        self.loops = ProblemGroup.objects.create(name='loop', full_name='Loops')
        self.graphs = ProblemGroup.objects.create(name='gra', full_name='Graphs')
        self.problems = {}
        for code, group in (('a1', self.arrays), ('a2', self.arrays), ('a3', self.arrays), ('a4', self.arrays),
                            ('l1', self.loops), ('l2', self.loops), ('g1', self.graphs)):
            p = Problem.objects.create(code=code, name='P ' + code, description='x', group=group, time_limit=1,
                                       memory_limit=65536, points=100, partial=True, is_public=True)
            p.types.set([ptype])
            self.problems[code] = p

    def submit(self, profile, code, points, when=None):
        problem = self.problems[code]
        sub = Submission.objects.create(user=profile, problem=problem, language=self.language, status='D',
                                        result='AC' if points >= problem.points else 'WA', points=points)
        if when is not None:
            Submission.objects.filter(pk=sub.pk).update(date=when)
        return sub


class WeekAverageTest(LearningBase):
    def test_none_without_work(self):
        self.assertIsNone(learning.week_average(self.me))

    def test_mean_of_best_per_problem_and_quiz_attempts(self):
        self.submit(self.me, 'a1', 40)
        self.submit(self.me, 'a1', 100)      # best on a1 counts, not the first try
        self.submit(self.me, 'a2', 50)
        quiz = Quiz.objects.create(title='Q', slug='lr-q', mode='practice', is_public=True, creator=self.me)
        QuizAttempt.objects.create(quiz=quiz, user=self.me, finished=timezone.now(), seed=1, score=6, max_score=10)
        # (1.0 + 0.5 + 0.6) / 3 * 10
        self.assertEqual(learning.week_average(self.me), 7.0)

    def test_old_and_invalidated_work_is_ignored(self):
        self.submit(self.me, 'a1', 100, when=timezone.now() - timedelta(days=9))
        quiz = Quiz.objects.create(title='Q', slug='lr-q2', mode='practice', is_public=True, creator=self.me)
        QuizAttempt.objects.create(quiz=quiz, user=self.me, finished=timezone.now(), seed=1, score=10, max_score=10,
                                   invalidated=True)
        QuizAttempt.objects.create(quiz=quiz, user=self.me, seed=2, score=10, max_score=10)   # not finished
        self.assertIsNone(learning.week_average(self.me))


class HeatGridTest(LearningBase):
    def test_shape_and_levels(self):
        now = timezone.now()
        for _i in range(3):
            self.submit(self.me, 'a1', 0, when=now)
        self.submit(self.me, 'a2', 0, when=now - timedelta(days=1))
        grid = learning.heat_grid(self.me, weeks=12)
        self.assertEqual(len(grid), 84)
        today = timezone.localdate()
        by_day = {c['day']: c for c in grid}
        self.assertEqual(by_day[today]['count'], 3)
        self.assertEqual(by_day[today]['level'], 4)
        self.assertEqual(sum(1 for c in grid if c['level'] > 0), 2)
        # row-major: 12 columns per weekday row; the last cell of row `weekday` belongs to this week
        self.assertEqual(grid[today.weekday() * 12 + 11]['day'], today)

    def test_other_users_do_not_count(self):
        self.submit(self.other, 'a1', 100)
        self.assertTrue(all(c['count'] == 0 for c in learning.heat_grid(self.me, weeks=26)))
        self.assertEqual(len(learning.heat_grid(self.me, weeks=26)), 182)


class TopicSkillsTest(LearningBase):
    def test_percent_is_solved_over_group_total(self):
        self.submit(self.me, 'a1', 100)
        self.submit(self.me, 'a1', 100)        # solving twice counts once
        self.submit(self.me, 'a2', 100)
        self.submit(self.me, 'a3', 30)          # tried, not solved
        self.submit(self.me, 'l1', 100)
        skills = {s['name']: s for s in learning.topic_skills(self.me)}
        self.assertEqual(skills['Arrays']['percent'], 50)          # 2 of 4
        self.assertEqual((skills['Arrays']['solved'], skills['Arrays']['total']), (2, 4))
        self.assertEqual(skills['Loops']['percent'], 50)           # 1 of 2
        self.assertNotIn('Graphs', skills)                         # never tried

    def test_most_active_first_and_limited(self):
        for _i in range(5):
            self.submit(self.me, 'l1', 0)
        self.submit(self.me, 'a1', 100)
        names = [s['name'] for s in learning.topic_skills(self.me)]
        self.assertEqual(names, ['Loops', 'Arrays'])
        self.assertEqual(len(learning.topic_skills(self.me, limit=1)), 1)

    def test_private_problems_are_not_counted(self):
        Problem.objects.filter(code='a2').update(is_organization_private=True)
        self.submit(self.me, 'a2', 100)
        self.assertEqual(learning.topic_skills(self.me), [])
        self.submit(self.me, 'a1', 100)
        self.assertEqual(learning.topic_skills(self.me)[0]['total'], 3)

    def test_empty_for_new_user(self):
        self.assertEqual(learning.topic_skills(self.me), [])


class BadgeTest(LearningBase):
    def test_computed_badges_only_when_earned(self):
        self.assertEqual(learning.earned_badges(self.me, best_streak=3, solved=9), [])
        got = learning.earned_badges(self.me, best_streak=7, solved=100)
        self.assertEqual([(b['kind'], b['name']) for b in got], [('streak', 7), ('solved', 100)])
        got = learning.earned_badges(self.me, best_streak=45, solved=12)
        self.assertEqual([(b['kind'], b['name']) for b in got], [('streak', 30), ('solved', 10)])

    def test_admin_badges_come_first(self):
        badge = Badge.objects.create(name='Winner', mini='https://example.com/w.png')
        self.me.badges.add(badge)
        got = learning.earned_badges(self.me, best_streak=0, solved=0)
        self.assertEqual(got, [{'name': 'Winner', 'image': 'https://example.com/w.png', 'computed': False}])


class ClassesAndNavTest(LearningBase):
    def test_my_classes_and_roles(self):
        a = Classroom.objects.create(name='10 Tin', slug='10-tin', school_year='2026-2027')
        b = Classroom.objects.create(name='Old', slug='old', school_year='2020-2021', is_archived=True)
        ClassMember.objects.create(classroom=a, user=self.me, role=RoleInClass.STUDENT)
        ClassMember.objects.create(classroom=b, user=self.me, role=RoleInClass.STUDENT)
        rows = learning.my_classes(self.me)
        self.assertEqual([r['classroom'].name for r in rows], ['10 Tin'])
        self.assertTrue(rows[0]['is_student'])

    def test_nav_menu_orgs(self):
        org = Organization.objects.create(name='School', slug='school', short_name='cb', about='x')
        self.me.organizations.add(org)
        org.admins.add(self.me)
        rows = learning.nav_menu_orgs(self.me.user)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['is_admin'])
        self.assertEqual(rows[0]['initials'], 'CB')
        self.assertEqual(learning.nav_menu_orgs(self.other.user), [])

    def test_initials(self):
        self.assertEqual(learning.initials('Nguyễn Minh Anh'), 'NA')
        self.assertEqual(learning.initials('hs01'), 'HS')
        self.assertEqual(learning.initials(''), '?')


class CourseProgressTest(LearningBase):
    def setUp(self):
        super().setUp()
        self.course = Course.objects.create(name='Intro', slug='intro', is_public=True, is_open=True)
        for n, codes in enumerate((('a1', 'a2'), ('l1',), ()), start=1):
            lesson = CourseLesson.objects.create(course=self.course, title='L%d' % n, order=n)
            for k, code in enumerate(codes, start=1):
                CourseLessonProblem.objects.create(lesson=lesson, problem=self.problems[code], order=k, points=100)
        CourseRole.objects.create(course=self.course, user=self.me, role='ST')

    def test_progress_counts_solved_problems(self):
        self.submit(self.me, 'a1', 100)
        self.submit(self.me, 'l1', 20)
        row = learning.course_progress_map(self.me, [self.course])[self.course.id]
        self.assertEqual((row['solved'], row['total'], row['percent'], row['lessons']), (1, 3, 33, 3))

    def test_continue_courses(self):
        rows = learning.continue_courses(self.me)
        self.assertEqual([r['course'].slug for r in rows], ['intro'])
        self.assertEqual(rows[0]['progress']['percent'], 0)
        self.assertEqual(learning.continue_courses(self.other), [])
        self.assertEqual([c.slug for c in learning.open_courses(exclude=[self.course.id])], [])
        self.assertEqual([c.slug for c in learning.open_courses()], ['intro'])


class PagesTest(LearningBase):
    def setUp(self):
        super().setUp()
        self.course = Course.objects.create(name='Intro', slug='intro', is_public=True, is_open=True)
        lesson = CourseLesson.objects.create(course=self.course, title='L1', order=1)
        CourseLessonProblem.objects.create(lesson=lesson, problem=self.problems['a1'], order=1, points=100)
        CourseRole.objects.create(course=self.course, user=self.me, role='ST')
        self.submit(self.me, 'a1', 100)

    def test_home_for_member_and_guest(self):
        self.client.force_login(self.me.user)
        html = self.client.get(reverse('home')).content.decode()
        for marker in ('lh-band', 'lh-heat', 'lh-course'):
            self.assertIn(marker, html)
        self.client.logout()
        html = self.client.get(reverse('home')).content.decode()
        self.assertIn('lh-band', html)
        self.assertNotIn('lh-heat', html)

    def test_profile_shows_skills_activity_and_badges(self):
        self.client.force_login(self.me.user)
        html = self.client.get(reverse('user_page', args=[self.me.user.username])).content.decode()
        for marker in ('pf-avatar', 'pf-heat', 'pf-skill', 'Arrays'):
            self.assertIn(marker, html)
        self.assertEqual(html.count('class="pf-heat"'), 1)

    def test_course_list_progress_only_for_members(self):
        self.client.force_login(self.me.user)
        self.assertIn('crs-progress', self.client.get(reverse('course_list')).content.decode())
        self.client.force_login(self.other.user)
        html = self.client.get(reverse('course_list') + '?tab=all').content.decode()
        self.assertNotIn('crs-progress', html)
        self.client.logout()
        self.assertNotIn('crs-progress', self.client.get(reverse('course_list')).content.decode())

    def test_course_and_lesson_pages(self):
        self.client.force_login(self.me.user)
        self.assertEqual(self.client.get(reverse('course_detail', args=[self.course.slug])).status_code, 200)
        lesson = self.course.lessons.first()
        self.assertEqual(self.client.get(reverse('course_lesson', args=[self.course.slug, lesson.id])).status_code, 200)
        ranking = self.client.get(reverse('course_lesson_ranking', args=[self.course.slug, lesson.id]))
        self.assertEqual(ranking.status_code, 200)
