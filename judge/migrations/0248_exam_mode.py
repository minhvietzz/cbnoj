from django.db import migrations, models
import django.db.models.deletion


def backfill_scores(apps, schema_editor):
    """Old attempts only stored right/wrong per question: derive the points from it."""
    QuizAttempt = apps.get_model('judge', 'QuizAttempt')
    QuizQuestion = apps.get_model('judge', 'QuizQuestion')
    points = {}
    for attempt in QuizAttempt.objects.filter(finished__isnull=False).iterator():
        if attempt.quiz_id not in points:
            points[attempt.quiz_id] = {str(q.id): q.points for q in QuizQuestion.objects.filter(quiz_id=attempt.quiz_id)}
        weights = points[attempt.quiz_id]
        attempt.scores = {qid: (weights.get(qid, 0) if ok else 0) for qid, ok in (attempt.results or {}).items()}
        attempt.save(update_fields=['scores'])


class Migration(migrations.Migration):

    dependencies = [
        ('judge', '0247_view_server_status_permission'),
    ]

    operations = [
        # --- question kinds (tf4) -------------------------------------------------------------------------
        migrations.AlterField(
            model_name='bankquestion',
            name='kind',
            field=models.CharField(choices=[('single', 'Single choice'), ('multi', 'Multiple choice'), ('short', 'Short answer'), ('tf4', 'True/False (4 statements)')], default='single', max_length=6, verbose_name='type'),
        ),
        migrations.AlterField(
            model_name='quizquestion',
            name='kind',
            field=models.CharField(choices=[('single', 'Single choice'), ('multi', 'Multiple choice'), ('short', 'Short answer'), ('tf4', 'True/False (4 statements)')], default='single', max_length=6, verbose_name='type'),
        ),
        migrations.AddField(
            model_name='quizquestion',
            name='section',
            field=models.CharField(blank=True, help_text='Optional heading such as "Part I"; consecutive questions share a section.', max_length=60, verbose_name='section'),
        ),
        migrations.AddField(
            model_name='banktag',
            name='group',
            field=models.CharField(choices=[('topic', 'Topic'), ('track', 'Track')], default='topic', max_length=5, verbose_name='group'),
        ),

        # --- quiz: mock exam settings ---------------------------------------------------------------------
        migrations.AddField(
            model_name='quiz',
            name='mode',
            field=models.CharField(choices=[('practice', 'Practice'), ('exam', 'Mock exam')], db_index=True, default='practice', max_length=8, verbose_name='mode'),
        ),
        migrations.AddField(
            model_name='quiz',
            name='course',
            field=models.ForeignKey(blank=True, help_text='Required for mock exams: only members of the course can take them.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='quizzes', to='judge.course', verbose_name='course'),
        ),
        migrations.AddField(
            model_name='quiz',
            name='track',
            field=models.CharField(blank=True, choices=[('', 'Not specified'), ('ict', 'Applied informatics'), ('cs', 'Computer science')], default='', max_length=3, verbose_name='track'),
        ),
        migrations.AddField(
            model_name='quiz',
            name='start_time',
            field=models.DateTimeField(blank=True, help_text='Mock exam only. Nobody can start before this time.', null=True, verbose_name='exam start'),
        ),
        migrations.AddField(
            model_name='quiz',
            name='end_time',
            field=models.DateTimeField(blank=True, help_text='Mock exam only. Every attempt is closed at this time.', null=True, verbose_name='exam end'),
        ),
        migrations.AddField(
            model_name='quiz',
            name='proctoring',
            field=models.CharField(choices=[('off', 'Off'), ('light', 'Light (block copy and right click)'), ('strict', 'Strict (fullscreen lock and monitoring)')], default='off', max_length=6, verbose_name='proctoring'),
        ),
        migrations.AddField(
            model_name='quiz',
            name='max_violations',
            field=models.PositiveIntegerField(default=3, help_text='0 means never auto-submit.', verbose_name='violations before auto-submit'),
        ),
        migrations.AddField(
            model_name='quiz',
            name='results_release',
            field=models.CharField(choices=[('immediate', 'Right after submitting'), ('after_end', 'After the exam window closes'), ('manual', 'When the teacher publishes them')], default='immediate', max_length=9, verbose_name='release results'),
        ),
        migrations.AddField(
            model_name='quiz',
            name='results_published',
            field=models.BooleanField(default=False, help_text='Used when results are released manually.', verbose_name='results published'),
        ),
        migrations.AddField(
            model_name='quiz',
            name='rules_text',
            field=models.TextField(blank=True, verbose_name='exam rules'),
        ),

        # --- attempts -------------------------------------------------------------------------------------
        migrations.AddField(
            model_name='quizattempt',
            name='scores',
            field=models.JSONField(blank=True, default=dict, help_text='Points earned per question id.'),
        ),
        migrations.AddField(
            model_name='quizattempt',
            name='auto_submitted',
            field=models.BooleanField(default=False, verbose_name='auto-submitted'),
        ),
        migrations.AddField(
            model_name='quizattempt',
            name='invalidated',
            field=models.BooleanField(default=False, help_text='Excluded from rankings and statistics.', verbose_name='invalidated'),
        ),
        migrations.AddField(
            model_name='quizattempt',
            name='violation_count',
            field=models.PositiveIntegerField(default=0, verbose_name='violations'),
        ),
        migrations.AddField(
            model_name='quizattempt',
            name='last_heartbeat',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='quizattempt',
            name='session_key',
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name='quizattempt',
            name='ip',
            field=models.GenericIPAddressField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='quizattempt',
            name='user_agent',
            field=models.CharField(blank=True, max_length=255),
        ),

        # --- new tables -----------------------------------------------------------------------------------
        migrations.CreateModel(
            name='QuizViolation',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('fullscreen_exit', 'Left fullscreen'), ('tab_hidden', 'Switched tab or window'), ('blur', 'Lost focus'), ('copy', 'Copy attempt'), ('paste', 'Paste attempt'), ('contextmenu', 'Right click'), ('print', 'Print attempt'), ('shortcut', 'Blocked shortcut'), ('devtools', 'Possible developer tools'), ('reload', 'Page reload'), ('second_session', 'Opened in another tab or device'), ('offline', 'Connection lost')], max_length=20, verbose_name='type')),
                ('detail', models.CharField(blank=True, max_length=255, verbose_name='detail')),
                ('counted', models.BooleanField(default=False)),
                ('created', models.DateTimeField(auto_now_add=True, verbose_name='time')),
                ('attempt', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='violations', to='judge.quizattempt', verbose_name='attempt')),
            ],
            options={
                'verbose_name': 'quiz violation',
                'verbose_name_plural': 'quiz violations',
                'ordering': ('created', 'id'),
            },
        ),
        migrations.CreateModel(
            name='QuizTopicStat',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('answered', models.PositiveIntegerField(default=0)),
                ('correct', models.PositiveIntegerField(default=0)),
                ('weighted_answered', models.FloatField(default=0, help_text='Questions weighted by difficulty.')),
                ('weighted_correct', models.FloatField(default=0)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('tag', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='user_stats', to='judge.banktag', verbose_name='tag')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='quiz_topic_stats', to='judge.profile', verbose_name='user')),
            ],
            options={
                'verbose_name': 'quiz topic statistic',
                'verbose_name_plural': 'quiz topic statistics',
                'unique_together': {('user', 'tag')},
            },
        ),
        migrations.CreateModel(
            name='QuizProfileStat',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('practice_sessions', models.PositiveIntegerField(default=0, verbose_name='practice sessions')),
                ('exams_taken', models.PositiveIntegerField(default=0, verbose_name='mock exams taken')),
                ('questions_answered', models.PositiveIntegerField(default=0, verbose_name='questions answered')),
                ('questions_correct', models.PositiveIntegerField(default=0, verbose_name='questions correct')),
                ('avg_exam_score', models.FloatField(default=0, verbose_name='average exam score (/10)')),
                ('best_exam_score', models.FloatField(default=0, verbose_name='best exam score (/10)')),
                ('level', models.CharField(blank=True, choices=[('', 'Not rated'), ('weak', 'Weak'), ('average', 'Average'), ('good', 'Good'), ('excellent', 'Excellent')], default='', max_length=9, verbose_name='level')),
                ('level_score', models.FloatField(default=0, verbose_name='level score (/10)')),
                ('updated', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='quiz_stat', to='judge.profile', verbose_name='user')),
            ],
            options={
                'verbose_name': 'quiz user statistic',
                'verbose_name_plural': 'quiz user statistics',
                'ordering': ('-level_score',),
            },
        ),

        migrations.RunPython(backfill_scores, migrations.RunPython.noop),
    ]
