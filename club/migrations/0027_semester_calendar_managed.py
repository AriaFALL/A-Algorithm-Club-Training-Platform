from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('club', '0026_audit_reward_consistency')]
    operations = [migrations.AddField(model_name='semester', name='calendar_managed',
                                     field=models.BooleanField(default=False))]
