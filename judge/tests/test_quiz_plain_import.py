import io
import zipfile
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from judge.models import BankQuestion, Profile, Quiz, Subject
from judge.utils import quiz_import_plain as qip

quiz_enabled = skipUnless(getattr(settings, 'QUIZ_ENABLED', False), 'the quiz feature is switched off')

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" ' \
    'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"'


def run(text, u=False, b=False):
    props = ('<w:u w:val="single"/>' if u else '') + ('<w:b/>' if b else '')
    return '<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % ('<w:rPr>%s</w:rPr>' % props if props else '', text)


def para(*runs):
    return '<w:p>%s</w:p>' % ''.join(r if r.startswith('<') else run(r) for r in runs)


def make_docx(body):
    xml = '<?xml version="1.0" encoding="UTF-8"?><w:document %s><w:body>%s</w:body></w:document>' % (W, body)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('word/document.xml', xml)
    return buffer.getvalue()


def make_pdf(lines):
    """A one-page PDF with plain Helvetica text (ASCII only)."""
    escaped = [text.replace('(', '\\(').replace(')', '\\)') for text in lines]
    content = 'BT /F1 11 Tf 14 TL 40 800 Td ' + ' '.join('(%s) Tj T*' % text for text in escaped) + ' ET'
    objects = [
        '<< /Type /Catalog /Pages 2 0 R >>',
        '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R '
        '/Resources << /Font << /F1 5 0 R >> >> >>',
        '<< /Length %d >>\nstream\n%s\nendstream' % (len(content), content),
        '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    ]
    out, offsets = b'%PDF-1.4\n', []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += ('%d 0 obj\n%s\nendobj\n' % (number, body)).encode('latin-1')
    start = len(out)
    out += ('xref\n0 %d\n0000000000 65535 f \n' % (len(objects) + 1)).encode()
    for offset in offsets:
        out += ('%010d 00000 n \n' % offset).encode()
    out += ('trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objects) + 1, start)).encode()
    return out


SAMPLE = """ĐỀ KIỂM TRA
PHẦN I. Câu trắc nghiệm nhiều phương án lựa chọn
Câu 1. Thủ đô của Việt Nam là
A. Hà Nội
B. Huế C. Đà Nẵng D. Hồ Chí Minh
Đáp án: A
Câu 2: Giao thức nào dùng để truyền trang web? A. FTP B. HTTP C. SMTP D. SSH
Câu 3. Quan sát hình sau, thiết bị nào là router?
A. Thiết bị 1
B. Thiết bị 2
Phần II. Câu trắc nghiệm đúng sai
Câu 4. Về mạng máy tính:
a) IP định danh thiết bị.
b) HTTP là giao thức thư.
c) Router nối mạng.
d) DNS dịch tên miền.
PHẦN III. Câu trắc nghiệm trả lời ngắn
Câu 5. 3 + 4 bằng bao nhiêu?
Câu 6. Một byte có bao nhiêu bit?
Đáp án: 8
BẢNG ĐÁP ÁN
1-A 2-B 3-B
4: a-Đ b-S c-Đ d-Đ
5-7
"""


class PlainParserTests(SimpleTestCase):
    def parse(self, text):
        return qip.parse_plain_text(text)

    def test_sample_paper(self):
        result = self.parse(SAMPLE)
        q = result['questions']
        self.assertEqual([x['kind'] for x in q], ['single', 'single', 'single', 'tf4', 'short', 'short'])
        self.assertEqual([o['correct'] for o in q[0]['options']], [True, False, False, False])
        self.assertEqual(q[0]['options'][3]['text'], 'Hồ Chí Minh')            # four options on two lines
        self.assertEqual([o['text'] for o in q[1]['options']], ['FTP', 'HTTP', 'SMTP', 'SSH'])   # inline options
        self.assertEqual(q[1]['text'], 'Giao thức nào dùng để truyền trang web?')
        self.assertEqual([o['correct'] for o in q[1]['options']], [False, True, False, False])   # from the table
        self.assertIn('figure', q[2]['warn'])
        self.assertEqual([o['correct'] for o in q[3]['options']], [True, False, True, True])      # tf from the table
        self.assertEqual(q[4]['answers'], ['7'])
        self.assertEqual(q[5]['answers'], ['8'])                                                  # "Đáp án: 8"
        self.assertTrue(result['has_key'])
        self.assertNotIn('no_answer', q[0]['warn'] + q[1]['warn'])

    def test_missing_answer_and_options(self):
        q = self.parse('Câu 1. Gì đó?\nA. x\nB. y\nCâu 2. Chỉ có đề\nA. duy nhất\nCâu 3. Đúng\nA. a\nB. b\n'
                       'Đáp án: B')['questions']
        self.assertIn('no_answer', q[0]['warn'])
        self.assertIn('few_options', q[1]['warn'])
        self.assertEqual(q[2]['options'][1]['correct'], True)

    def test_multi_answer_and_bad_letter(self):
        q = self.parse('Câu 1. Chọn các số chẵn\nA. 2\nB. 3\nC. 4\nD. 5\nĐáp án: A, C\n'
                       'Câu 2. X\nA. a\nB. b\nĐáp án: E')['questions']
        self.assertEqual(q[0]['kind'], 'multi')
        self.assertIn('bad_answer', q[1]['warn'])

    def test_bare_numbers_lowercase_options_and_english(self):
        q = self.parse('1. What is 2+2?\na. 3\nb. 4\nc. 5\nAnswer: b\n2) Next one\nA) x\nB) y\nAnswer: A')['questions']
        self.assertEqual(len(q), 2)
        self.assertEqual([o['correct'] for o in q[0]['options']], [False, True, False])
        self.assertEqual(q[1]['options'][0]['correct'], True)
        q = self.parse('Question 1. Pick\nA. one\nB. two\nQuestion 2. Pick\nA. one\nB. two')['questions']
        self.assertEqual(len(q), 2)

    def test_two_row_table(self):
        q = self.parse('Câu 1. a?\nA. 1\nB. 2\nCâu 2. b?\nA. 1\nB. 2\nCâu 3. c?\nA. 1\nB. 2\n'
                       'Đáp án\nCâu 1 2 3\nĐáp án B A B')['questions']
        self.assertEqual([[o['correct'] for o in x['options']] for x in q],
                         [[False, True], [True, False], [False, True]])

    def test_tf_inline_answer_forms(self):
        text = 'Phần II. Đúng sai\nCâu 1. a\na) 1\nb) 2\nc) 3\nd) 4\nĐáp án: ĐSSĐ\n'
        q = self.parse(text)['questions'][0]
        self.assertEqual([o['correct'] for o in q['options']], [True, False, False, True])
        q = self.parse('Câu 1. a\na) 1\nb) 2\nc) 3\nd) 4\nĐáp án: a, c')['questions'][0]
        self.assertEqual(q['kind'], 'tf4')       # four lowercase a) b) c) d) without a section heading
        self.assertEqual([o['correct'] for o in q['options']], [True, False, True, False])

    def test_no_questions(self):
        with self.assertRaises(qip.PlainImportError):
            self.parse('Chỉ là một đoạn văn bình thường.\nKhông có câu hỏi.')

    def test_question_limit(self):
        text = '\n'.join('Câu %d. q\nA. a\nB. b\nĐáp án: A' % i for i in range(1, qip.MAX_QUESTIONS + 2))
        with self.assertRaises(qip.PlainImportError):
            self.parse(text)


class DocxTests(SimpleTestCase):
    def test_underline_marks_correct_option(self):
        body = (para('Câu 1. Chọn đúng') + para(run('A.', u=True), ' Một') + para('B. Hai') + para('C. Ba') +
                para('Câu 2. Chọn đúng') + para('A. x') + para('B. ', run('y', b=True)))
        result = qip.parse_plain_file('de.docx', make_docx(body))
        q = result['questions']
        self.assertEqual(result['format'], 'Word')
        self.assertEqual([o['correct'] for o in q[0]['options']], [True, False, False])
        self.assertEqual([o['correct'] for o in q[1]['options']], [False, True])

    def test_all_options_marked_is_ignored(self):
        body = para('Câu 1. X') + para(run('A. a', b=True)) + para(run('B. b', b=True))
        q = qip.parse_plain_file('de.docx', make_docx(body))['questions'][0]
        self.assertIn('no_answer', q['warn'])

    def test_table_key_formula_and_picture(self):
        omml = ('<m:oMath><m:f><m:num><m:r><m:t>1</m:t></m:r></m:num><m:den><m:r><m:t>x</m:t></m:r></m:den></m:f>'
                '</m:oMath>')
        picture = '<w:r><w:drawing/></w:r>'
        body = (para('Câu 1. Giá trị ', omml, ' là') + para('A. 1') + para('B. 2') +
                para('Câu 2. Xem sơ đồ ', picture) + para('A. 1') + para('B. 2') +
                '<w:tbl><w:tr><w:tc>%s</w:tc><w:tc>%s</w:tc><w:tc>%s</w:tc></w:tr>'
                '<w:tr><w:tc>%s</w:tc><w:tc>%s</w:tc><w:tc>%s</w:tc></w:tr></w:tbl>' % (
                    para('1'), para('2'), para('3'), para('B'), para('A'), para('C')))
        q = qip.parse_plain_file('de.docx', make_docx(body))['questions']
        self.assertIn('\\frac{1}{x}', q[0]['text'])
        self.assertIn('formula', q[0]['warn'])
        self.assertIn('figure', q[1]['warn'])
        self.assertEqual([o['correct'] for o in q[0]['options']], [False, True])
        self.assertEqual([o['correct'] for o in q[1]['options']], [True, False])

    def test_bad_files(self):
        with self.assertRaises(qip.PlainImportError):
            qip.parse_plain_file('x.docx', b'not a zip')
        with self.assertRaises(qip.PlainImportError):
            qip.parse_plain_file('x.doc', b'abc')
        with self.assertRaises(qip.PlainImportError):
            qip.parse_plain_file('x.docx', b'0' * (qip.MAX_BYTES + 1))
        bomb = ('<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "aaaa">]><w:document %s><w:body>&a;</w:body>'
                '</w:document>' % W)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('word/document.xml', bomb)
        with self.assertRaises(qip.PlainImportError):
            qip.parse_plain_file('x.docx', buffer.getvalue())


class PdfTests(SimpleTestCase):
    def test_text_pdf(self):
        lines = ['Cau 1. The capital of Vietnam is', 'A. Hanoi', 'B. Hue', 'C. Da Nang', 'D. Saigon', 'Dap an: A',
                 'Cau 2. Pick the protocol for web pages', 'A. FTP', 'B. HTTP', 'Answer: B']
        result = qip.parse_plain_file('de.pdf', make_pdf(lines))
        self.assertEqual(result['format'], 'PDF')
        q = result['questions']
        self.assertEqual(len(q), 2)
        self.assertEqual([o['correct'] for o in q[1]['options']], [False, True])

    def test_pdf_without_text(self):
        with self.assertRaises(qip.PlainImportError) as ctx:
            qip.parse_plain_file('scan.pdf', make_pdf(['']))
        self.assertIn('scan', str(ctx.exception))

    def test_broken_pdf(self):
        with self.assertRaises(qip.PlainImportError):
            qip.parse_plain_file('x.pdf', b'%PDF-1.4 garbage')


@quiz_enabled
class PlainImportViewTests(TestCase):
    def setUp(self):
        self.client.defaults['HTTP_ACCEPT_LANGUAGE'] = 'en'
        user_model = get_user_model()
        self.teacher_user = user_model.objects.create_user(username='teacher', password='pw')
        self.teacher_user.user_permissions.add(Permission.objects.get(codename='add_quiz'))
        self.teacher = Profile.objects.create(user=self.teacher_user)
        self.student = Profile.objects.create(user=user_model.objects.create_user(username='student', password='pw'))
        self.subject = Subject.objects.get(slug='tin-hoc')
        self.docx = make_docx(
            para('Câu 1. Thủ đô?') + para(run('A.', u=True), ' Hà Nội') + para('B. Huế') +
            para('Câu 2. Hai cộng hai?') + para('Đáp án: 4') +
            para('Câu 3. Chưa có đáp án') + para('A. x') + para('B. y'))

    def upload(self, data=None, name='de.docx'):
        return self.client.post(reverse('bank_import_plain'),
                                {'file': SimpleUploadedFile(name, data or self.docx)})

    def test_permission(self):
        self.client.login(username='student', password='pw')
        self.assertEqual(self.client.get(reverse('bank_import_plain')).status_code, 403)
        self.assertEqual(self.upload().status_code, 403)
        self.assertEqual(self.client.get(reverse('bank_import_plain_preview')).status_code, 403)

    def test_upload_preview_writes_nothing(self):
        self.client.login(username='teacher', password='pw')
        self.assertEqual(self.client.get(reverse('bank_import_plain')).status_code, 200)
        resp = self.upload()
        self.assertRedirects(resp, reverse('bank_import_plain_preview'))
        page = self.client.get(reverse('bank_import_plain_preview'))
        self.assertContains(page, 'Hà Nội')
        self.assertContains(page, '1 questions need checking')
        self.assertEqual(BankQuestion.objects.count(), 0)
        # applying edits and failing validation still writes nothing
        resp = self.client.post(reverse('bank_import_plain_preview'),
                                {'action': 'save', 'subject': self.subject.id, 'mode': 'bank'})
        self.assertContains(resp, 'Choose the correct option.')
        self.assertEqual(BankQuestion.objects.count(), 0)

    def test_scan_error_and_oversize(self):
        self.client.login(username='teacher', password='pw')
        resp = self.upload(make_pdf(['']), 'scan.pdf')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'scan')
        resp = self.upload(b'0' * (qip.MAX_BYTES + 1))
        self.assertContains(resp, 'larger than 10 MB')

    def test_edit_and_save_to_bank_and_quiz(self):
        self.client.login(username='teacher', password='pw')
        self.upload()
        url = reverse('bank_import_plain_preview')
        post = {'action': 'save', 'subject': self.subject.id, 'tags': 'Thuật toán, Mạng', 'level': '2',
                'mode': 'quiz', 'title': 'De thu', 'ok_2': '1',
                'text_0': 'Thủ đô?', 'text_1': 'Hai cộng hai?', 'text_2': 'Chưa có đáp án',
                'kind_0': 'single', 'kind_1': 'short', 'kind_2': 'single', 'ans_1': '4 | bốn', 'ok_0': '0'}
        resp = self.client.post(url, post)
        self.assertEqual(Quiz.objects.count(), 1, getattr(resp, 'content', b'')[:300])
        quiz = Quiz.objects.get()
        self.assertRedirects(resp, quiz.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual(quiz.questions.count(), 3)
        banks = BankQuestion.objects.order_by('id')
        self.assertEqual(banks.count(), 3)
        self.assertTrue(all(b.subject_id == self.subject.id and b.level == 2 for b in banks))
        self.assertEqual(sorted(t.name for t in banks[0].tags.all()), ['Mạng', 'Thuật toán'])
        self.assertEqual(banks[1].accepted_list(), ['4', 'bốn'])
        # uploading the same paper again: everything is a duplicate
        self.upload()
        self.client.post(url, dict(post, mode='bank'))
        self.assertEqual(BankQuestion.objects.count(), 3)

    def test_delete_question(self):
        self.client.login(username='teacher', password='pw')
        self.upload()
        resp = self.client.post(reverse('bank_import_plain_preview'), {
            'action': 'save', 'subject': self.subject.id, 'mode': 'bank', 'del_1': 'on', 'del_2': 'on',
            'ok_0': '0', 'kind_0': 'single'})
        self.assertRedirects(resp, reverse('bank_list'))
        self.assertEqual(BankQuestion.objects.count(), 1)
