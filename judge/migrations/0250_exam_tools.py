from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('judge', '0249_personal_practice'),
    ]

    operations = [
        migrations.AddField(
            model_name='quiz',
            name='extra_minutes',
            field=models.PositiveIntegerField(default=0, help_text='Added by a teacher during the exam, e.g. after an outage.', verbose_name='extra minutes for everyone'),
        ),
        migrations.AddField(
            model_name='quiz',
            name='seb_browser_key',
            field=models.CharField(blank=True, help_text='Optional. When set, the exam can only be taken in Safe Exam Browser configured with this Browser Exam Key.', max_length=64, verbose_name='Safe Exam Browser key'),
        ),
        migrations.AddField(
            model_name='quizattempt',
            name='extra_minutes',
            field=models.PositiveIntegerField(default=0, help_text='Extra time granted to this candidate only.', verbose_name='extra minutes'),
        ),
        migrations.AddIndex(
            model_name='quizattempt',
            index=models.Index(fields=['quiz', 'user'], name='quizattempt_quiz_user_idx'),
        ),
        migrations.AddIndex(
            model_name='quizattempt',
            index=models.Index(fields=['user', 'finished'], name='quizattempt_user_fin_idx'),
        ),
        migrations.AddIndex(
            model_name='quizattempt',
            index=models.Index(fields=['finished'], name='quizattempt_finished_idx'),
        ),
    ]
