from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from judge.models import ClassMember, Classroom, Organization, Profile, RoleInClass, Subject
from judge.utils import xlsx


def make_profile(username, **extra):
    user = get_user_model().objects.create_user(username, password='x', email=username + '@example.com', **extra)
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile


class ClassroomBase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='School', slug='school', short_name='SC', about='x')
        self.admin = make_profile('class_admin')
        self.org.admins.add(self.admin)
        self.teacher = make_profile('class_teacher')
        self.student = make_profile('class_student')
        self.other = make_profile('class_other')
        self.classroom = Classroom.objects.create(name='10A1', slug='10a1', organization=self.org,
                                                  school_year='2026-2027', join_code='JOIN1')
        ClassMember.objects.create(classroom=self.classroom, user=self.teacher, role=RoleInClass.HOMEROOM)
        ClassMember.objects.create(classroom=self.classroom, user=self.student, role=RoleInClass.STUDENT)

    def login(self, profile):
        self.client.force_login(profile.user)


class ClassroomModelTest(ClassroomBase):
    def test_default_subject_is_seeded(self):
        self.assertTrue(Subject.objects.filter(slug='tin-hoc').exists())

    def test_visibility_and_management(self):
        c = self.classroom
        self.assertTrue(c.is_visible_to(self.student.user))
        self.assertFalse(c.is_visible_to(self.other.user))
        self.assertTrue(c.is_visible_to(self.admin.user), 'organization admin sees every class of the organization')
        self.assertFalse(c.is_managed_by(self.student.user))
        self.assertTrue(c.is_managed_by(self.teacher.user))
        self.assertTrue(c.is_managed_by(self.admin.user))
        self.assertTrue(c.is_staffed_by(self.teacher.user))
        self.assertFalse(c.is_staffed_by(self.student.user))

    def test_class_without_organization(self):
        c = Classroom.objects.create(name='Team', slug='team')
        ClassMember.objects.create(classroom=c, user=self.student)
        self.assertTrue(c.is_visible_to(self.student.user))
        self.assertFalse(c.is_managed_by(self.student.user))
        self.assertFalse(c.is_visible_to(self.admin.user))


class ClassroomViewTest(ClassroomBase):
    def test_login_required(self):
        self.assertEqual(self.client.get(reverse('class_list')).status_code, 302)

    def test_my_classes_lists_only_mine(self):
        Classroom.objects.create(name='Hidden', slug='hidden')
        self.login(self.student)
        response = self.client.get(reverse('class_list'))
        self.assertContains(response, '10A1')
        self.assertNotContains(response, 'Hidden')

    def test_detail_hidden_from_outsiders(self):
        self.login(self.other)
        self.assertEqual(self.client.get(self.classroom.get_absolute_url()).status_code, 404)
        self.login(self.student)
        self.assertEqual(self.client.get(self.classroom.get_absolute_url()).status_code, 200)

    def test_student_cannot_create_or_edit(self):
        self.login(self.student)
        self.assertEqual(self.client.get(reverse('class_create')).status_code, 403)
        self.assertEqual(self.client.get(reverse('class_edit', args=('10a1',))).status_code, 403)
        self.assertEqual(self.client.get(reverse('class_import')).status_code, 403)

    def test_org_admin_creates_class_and_becomes_homeroom(self):
        self.login(self.admin)
        response = self.client.post(reverse('class_create'), {
            'name': '11 Tin', 'organization': self.org.id, 'school_year': '2026-2027', 'about': '',
            'join_code': '', 'subject': '',
        })
        self.assertEqual(response.status_code, 302)
        created = Classroom.objects.get(name='11 Tin')
        self.assertEqual(created.slug, '11-tin')
        self.assertEqual(created.get_role(self.admin), RoleInClass.HOMEROOM)

    def test_members_add_role_remove(self):
        self.login(self.teacher)
        url = reverse('class_members', args=('10a1',))
        self.client.post(url, {'action': 'add', 'usernames': 'class_other\nnobody', 'role': 'ST'})
        self.assertEqual(self.classroom.get_role(self.other), RoleInClass.STUDENT)
        member = ClassMember.objects.get(classroom=self.classroom, user=self.other)
        self.client.post(url, {'action': 'role', 'member': member.id, 'role': 'AS'})
        member.refresh_from_db()
        self.assertEqual(member.role, RoleInClass.ASSISTANT)
        self.client.post(url, {'action': 'remove', 'member': member.id})
        self.assertFalse(ClassMember.objects.filter(id=member.id).exists())

    def test_student_cannot_manage_members(self):
        self.login(self.student)
        response = self.client.post(reverse('class_members', args=('10a1',)),
                                    {'action': 'add', 'usernames': 'class_other'})
        self.assertEqual(response.status_code, 403)

    def test_last_teacher_cannot_be_removed_by_themselves(self):
        self.login(self.teacher)
        member = ClassMember.objects.get(classroom=self.classroom, user=self.teacher)
        self.client.post(reverse('class_members', args=('10a1',)), {'action': 'remove', 'member': member.id})
        self.assertTrue(ClassMember.objects.filter(id=member.id).exists())

    def test_join_by_code_adds_to_organization(self):
        self.login(self.other)
        response = self.client.post(reverse('class_join'), {'code': 'JOIN1'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.classroom.get_role(self.other), RoleInClass.STUDENT)
        self.assertTrue(self.other.organizations.filter(id=self.org.id).exists())
        self.login(self.admin)
        self.assertEqual(self.client.post(reverse('class_join'), {'code': 'WRONG'}).status_code, 404)


class ClassImportTest(ClassroomBase):
    def upload(self, content, name='list.csv', **extra):
        data = {'file': SimpleUploadedFile(name, content), 'organization': self.org.id, 'school_year': '2026-2027',
                'create_missing': 'on', 'add_to_org': 'on'}
        data.update(extra)
        return self.client.post(reverse('class_import'), data)

    def csv(self):
        return ('Họ tên,Tên truy cập,Email,Lớp,Vai trò\n'
                'A,class_other,,11B,Học sinh\n'
                'B,,class_student@example.com,11B,\n'
                'C,ghost,,11B,\n'
                'D,class_other,,,\n').encode('utf-8-sig')

    def test_dry_run_writes_nothing(self):
        self.login(self.admin)
        response = self.upload(self.csv(), dry_run='on')
        self.assertEqual(response.status_code, 200)
        report = response.context['report']
        self.assertEqual(report['matched'], 2)
        self.assertEqual(report['added'], 2)
        self.assertEqual(len(report['unmatched']), 1)
        self.assertEqual(report['no_class'], [5])
        self.assertFalse(Classroom.objects.filter(name='11B').exists())

    def test_apply_creates_class_and_members(self):
        self.login(self.admin)
        response = self.upload(self.csv())
        self.assertEqual(response.context['report']['added'], 2)
        c = Classroom.objects.get(name='11B')
        self.assertEqual(c.organization, self.org)
        self.assertEqual(c.get_role(self.other), RoleInClass.STUDENT)
        self.assertEqual(c.get_role(self.student), RoleInClass.STUDENT, 'matched by email')
        self.assertTrue(self.other.organizations.filter(id=self.org.id).exists())
        again = self.upload(self.csv())
        self.assertEqual(again.context['report']['already'], 2, 'importing twice does not duplicate')
        self.assertEqual(ClassMember.objects.filter(classroom=c).count(), 2)

    def test_xlsx_upload(self):
        self.login(self.admin)
        data = xlsx.build_xlsx(['Tên truy cập', 'Lớp'], [['class_other', '10A1']], 'Sheet')
        response = self.upload(data, name='list.xlsx')
        self.assertEqual(response.context['report']['added'], 1)
        self.assertEqual(self.classroom.get_role(self.other), RoleInClass.STUDENT)

    def test_bad_header_is_reported(self):
        self.login(self.admin)
        response = self.upload(b'a,b\n1,2\n')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)

    def test_teacher_cannot_create_classes(self):
        self.login(self.teacher)
        self.assertEqual(self.client.get(reverse('class_import')).status_code, 403)

    def test_cannot_import_into_foreign_organization(self):
        other_org = Organization.objects.create(name='Other', slug='other', short_name='OT', about='x')
        self.login(self.admin)
        response = self.upload(self.csv(), organization=other_org.id)
        self.assertTrue(response.context['form'].errors, 'the choice is limited to organizations you administer')

    def test_template_download(self):
        self.login(self.admin)
        response = self.client.get(reverse('class_import_template'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('Tên truy cập', response.content.decode('utf-8'))
