from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("club", "0005_team_admin_invite")]

    operations = [
        migrations.AddField(
            model_name="submission",
            name="visibility",
            field=models.CharField(
                choices=[
                    ("team", "团队成员可见"),
                    ("private", "仅管理员和本人可见"),
                ],
                default="team",
                max_length=10,
            ),
        ),
    ]
