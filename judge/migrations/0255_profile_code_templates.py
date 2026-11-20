from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('judge', '0254_profile_problem_ui'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='template_cpp',
            field=models.TextField(blank=True, max_length=20000, verbose_name='C++ template'),
        ),
        migrations.AddField(
            model_name='profile',
            name='template_c',
            field=models.TextField(blank=True, max_length=20000, verbose_name='C template'),
        ),
        migrations.AddField(
            model_name='profile',
            name='template_py',
            field=models.TextField(blank=True, max_length=20000, verbose_name='Python template'),
        ),
        migrations.AddField(
            model_name='profile',
            name='template_pas',
            field=models.TextField(blank=True, max_length=20000, verbose_name='Pascal template'),
        ),
    ]
