import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('judge', '0250_exam_tools'),
    ]

    operations = [
        migrations.AddField(
            model_name='courselesson',
            name='prerequisite',
            field=models.ForeignKey(blank=True, help_text='Students must reach the required score in this lesson first.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='unlocks', to='judge.courselesson', verbose_name='prerequisite lesson'),
        ),
        migrations.AddField(
            model_name='courselesson',
            name='prerequisite_percent',
            field=models.PositiveSmallIntegerField(default=60, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(100)], verbose_name='required score (%)'),
        ),
    ]
