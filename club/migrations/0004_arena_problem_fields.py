from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("club", "0003_alter_team_cleanup_delay_days")]
    operations = [
        migrations.RemoveField(model_name="arena", name="problem_url"),
        migrations.AddField(model_name="arena", name="samples", field=models.TextField(blank=True)),
        migrations.AddField(model_name="arena", name="judge_script", field=models.FileField(blank=True, upload_to="arena/scripts/%Y/%m/")),
    ]
