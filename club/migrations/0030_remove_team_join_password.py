from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('club', '0029_backfill_contest_solved')]
    operations = [migrations.RemoveField(model_name='team', name='join_password_hash')]
