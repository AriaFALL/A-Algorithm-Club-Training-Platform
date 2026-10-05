from django.db import migrations, models


def preserve_existing_archives(apps, schema_editor):
    Semester = apps.get_model('club', 'Semester')
    CleanupJob = apps.get_model('club', 'CleanupJob')
    Total = apps.get_model('club', 'SemesterMemberTotal')
    for job in CleanupJob.objects.filter(status='completed'):
        Semester.objects.filter(pk=job.semester_id).update(archived_at=job.finished_at or job.scheduled_for)
    for total in Total.objects.select_related('member'):
        total.display_name = total.member.display_name
        total.save(update_fields=['display_name'])


class Migration(migrations.Migration):
    dependencies = [('club', '0006_submission_visibility')]
    operations = [
        migrations.AddField(model_name='semester', name='archived_at', field=models.DateTimeField(null=True, blank=True)),
        migrations.AddField(model_name='cleanupjob', name='pending_files', field=models.JSONField(default=list, blank=True)),
        migrations.AddField(model_name='semestermembertotal', name='display_name', field=models.CharField(max_length=40, blank=True)),
        migrations.RunPython(preserve_existing_archives, migrations.RunPython.noop),
    ]
