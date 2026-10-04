from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("club", "0004_arena_problem_fields")]
    operations = [migrations.AddField(model_name="team", name="admin_invite_hash", field=models.CharField(blank=True, default="", max_length=128))]
