from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('judge', '0255_profile_code_templates'),
    ]

    operations = [
        migrations.AddField(
            model_name='quiz',
            name='questions_per_attempt',
            field=models.PositiveIntegerField(default=0, help_text='Each attempt draws this many random questions from the quiz. 0 means all questions.', verbose_name='questions per attempt'),
        ),
    ]
