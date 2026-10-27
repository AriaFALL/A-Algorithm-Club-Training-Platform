from django.db import migrations


def cancel_legacy_schedules(apps, schema_editor):
    Semester = apps.get_model('club', 'Semester')
    CleanupJob = apps.get_model('club', 'CleanupJob')
    alias = schema_editor.connection.alias
    CleanupJob.objects.using(alias).filter(semester__archived_at__isnull=True).exclude(status='completed').delete()
    Semester.objects.using(alias).filter(archived_at__isnull=True).update(cleanup_at=None)


class Migration(migrations.Migration):
    dependencies = [('club', '0013_parser_api_protocol')]
    operations = [migrations.RunPython(cancel_legacy_schedules, migrations.RunPython.noop)]
