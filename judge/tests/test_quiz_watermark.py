from urllib.parse import unquote

from django.conf import settings

from judge.models import Quiz
from judge.tests.test_quiz_exam import ExamTestCase


class WatermarkTest(ExamTestCase):
    """The exam page always carries a faint watermark: the site name and the account of the student."""

    def page(self):
        attempt = self.attempt()
        self.login('student')
        return self.client.get(reverse_attempt(self.quiz, attempt)).content.decode('utf-8')

    def watermark_text(self, html):
        start = html.index('class="qz-watermark"')
        chunk = html[start:html.index('>', start)]
        url = chunk.split('url(', 1)[1].split(')', 1)[0]
        self.assertTrue(url.startswith('data:image/svg+xml,'), 'must be a data URI, not a relative URL: ' + url[:40])
        return unquote(url[len('data:image/svg+xml,'):])

    def test_exam_page_has_site_name_and_account(self):
        text = self.watermark_text(self.page())
        self.assertIn('student', text)
        self.assertIn(settings.SITE_NAME, text)
        self.assertIn('<svg', text, 'the image is a real SVG, not escaped text')

    def test_watermark_is_present_without_proctoring(self):
        Quiz.objects.filter(pk=self.quiz.pk).update(proctoring='off')
        self.assertIn('student', self.watermark_text(self.page()))

    def test_only_one_watermark_is_drawn(self):
        html = self.page()
        self.assertEqual(html.count('qz-watermark" aria-hidden'), 1)
        self.assertNotIn("$('<div class=\"qz-watermark\"", html)

    def test_account_name_is_escaped(self):
        self.student.user.username = 'a<b>&"c'
        self.student.user.save()
        self.client.logout()
        self.assertTrue(self.client.login(username='a<b>&"c', password='pw'))
        attempt = self.attempt()
        html = self.client.get(reverse_attempt(self.quiz, attempt)).content.decode('utf-8')
        text = self.watermark_text(html)
        self.assertNotIn('a<b>', text)
        self.assertIn('a&lt;b&gt;', text)


def reverse_attempt(quiz, attempt):
    from django.urls import reverse
    return reverse('quiz_attempt', args=[quiz.slug, attempt.id])
