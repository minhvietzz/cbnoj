import io
import zipfile

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from judge.models import Course, CourseLesson, CourseRole, Profile


def make_profile(username):
    user = get_user_model().objects.create_user(username, password='pw')
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile


class CourseGradesExportTest(TestCase):
    def setUp(self):
        self.teacher = make_profile('export_teacher')
        self.student = make_profile('export_student')
        self.other = make_profile('export_other')
        self.course = Course.objects.create(name='Export course', slug='export-course', is_public=True)
        CourseRole.objects.create(course=self.course, user=self.teacher, role='TE')
        CourseRole.objects.create(course=self.course, user=self.student, role='ST')
        CourseLesson.objects.create(course=self.course, title='Bài đầu tiên', order=1, is_visible=True)
        self.url = reverse('course_grades', args=[self.course.slug])

    def login(self, profile):
        self.client.logout()
        self.assertTrue(self.client.login(username=profile.user.username, password='pw'))

    def test_teacher_gets_csv(self):
        self.login(self.teacher)
        response = self.client.get(self.url, {'export': 'csv'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('export-course-grades.csv', response['Content-Disposition'])
        lines = response.content.decode('utf-8-sig').splitlines()
        self.assertEqual(lines[0], 'Rank,Username,Name,Bài đầu tiên,Total,Max,Percent')
        self.assertTrue(any(line.split(',')[1] == 'export_student' for line in lines[1:]))

    def test_teacher_gets_a_valid_xlsx(self):
        self.login(self.teacher)
        response = self.client.get(self.url, {'export': 'xlsx'})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(zipfile.ZipFile(io.BytesIO(response.content)).testzip())

    def test_students_cannot_export(self):
        self.login(self.student)
        self.assertEqual(self.client.get(self.url, {'export': 'csv'}).status_code, 403)
        self.assertEqual(self.client.get(self.url, {'export': 'xlsx'}).status_code, 403)

    def test_page_shows_export_buttons_to_teachers_only(self):
        self.login(self.teacher)
        self.assertContains(self.client.get(self.url), 'export=xlsx')
        self.login(self.student)
        self.assertNotContains(self.client.get(self.url), 'export=xlsx')
