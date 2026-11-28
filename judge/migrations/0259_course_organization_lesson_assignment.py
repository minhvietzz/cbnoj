from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('judge', '0258_code_similarity'),
    ]

    operations = [
        migrations.AddField(
            model_name='course',
            name='organization',
            field=models.ForeignKey(blank=True, help_text='Optional. Members of the organization can open the course, and its administrators can edit it.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='courses', to='judge.organization', verbose_name='organization'),
        ),
        migrations.AddField(
            model_name='classassignment',
            name='lesson',
            field=models.ForeignKey(blank=True, help_text='A whole lesson: its problems and quizzes, including ones added later. For a list of problems it only records where they came from.', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='class_assignments', to='judge.courselesson', verbose_name='course lesson'),
        ),
        migrations.AlterField(
            model_name='classassignment',
            name='kind',
            field=models.CharField(choices=[('problem', 'Programming problems'), ('quiz', 'Quiz'), ('lesson', 'Whole course lesson')], default='problem', max_length=8, verbose_name='type'),
        ),
    ]
