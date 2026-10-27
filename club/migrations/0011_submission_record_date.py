from django.db import migrations, models
from django.utils import timezone


def backfill(apps, schema_editor):
    Submission = apps.get_model('club', 'Submission')
    for item in Submission.objects.all().iterator():
        Submission.objects.filter(pk=item.pk).update(record_date=timezone.localdate(item.submitted_at))


class Migration(migrations.Migration):
    dependencies = [('club', '0010_account_roles')]
    operations = [
        migrations.AddField(model_name='submission', name='record_date', field=models.DateField(default=timezone.localdate)),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
