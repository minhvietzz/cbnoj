from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('judge', '0252_quiz_passage'),
    ]

    operations = [
        migrations.AddField(
            model_name='quiz',
            name='organizations',
            field=models.ManyToManyField(blank=True, help_text='Optional. A mock exam without a course and with organizations is open only to their members.', related_name='quizzes', to='judge.organization', verbose_name='organizations'),
        ),
    ]
