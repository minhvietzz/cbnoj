from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('judge', '0253_quiz_organizations'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='problem_ui',
            field=models.CharField(choices=[('old', 'Old layout'), ('new', 'New layout (editor and try-run)')], default='old', max_length=3, verbose_name='problem page layout'),
        ),
    ]
