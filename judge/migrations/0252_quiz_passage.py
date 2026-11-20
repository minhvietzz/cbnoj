from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('judge', '0251_course_lesson_prerequisite'),
    ]

    operations = [
        migrations.AddField(
            model_name='quizquestion',
            name='passage',
            field=models.TextField(blank=True, help_text='Optional shared text shown beside the question in the exam room. Consecutive questions with the same text share one passage.', verbose_name='reading passage'),
        ),
    ]
