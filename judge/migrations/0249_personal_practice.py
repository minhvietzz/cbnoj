from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('judge', '0248_exam_mode'),
    ]

    operations = [
        migrations.AlterField(
            model_name='quiz',
            name='mode',
            field=models.CharField(choices=[('practice', 'Practice'), ('exam', 'Mock exam'), ('personal', 'Personal practice')], db_index=True, default='practice', max_length=8, verbose_name='mode'),
        ),
    ]
