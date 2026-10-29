from django.conf import settings
from django.db import migrations,models
import django.db.models.deletion


def backfill(apps,schema_editor):
    Grant=apps.get_model('club','WeeklyStreakGrant')
    for grant in Grant.objects.select_related('member').all():
        grant.team_id=grant.member.team_id
        grant.user_id=grant.member.user_id
        grant.save(update_fields=['team','user'])


class Migration(migrations.Migration):
    dependencies=[('club','0025_persisted_contest_calendar'),migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations=[
        migrations.AddField(model_name='contestsyncstate',name='progressed_at',field=models.DateTimeField(null=True)),
        migrations.AddField(model_name='purchase',name='request_id',field=models.UUIDField(null=True,unique=True)),
        migrations.AddField(model_name='weeklystreakgrant',name='team',field=models.ForeignKey(null=True,on_delete=django.db.models.deletion.CASCADE,to='club.team')),
        migrations.AddField(model_name='weeklystreakgrant',name='user',field=models.ForeignKey(null=True,on_delete=django.db.models.deletion.SET_NULL,to=settings.AUTH_USER_MODEL)),
        migrations.RunPython(backfill,migrations.RunPython.noop),
        migrations.AlterField(model_name='weeklystreakgrant',name='team',field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,to='club.team')),
        migrations.AlterField(model_name='weeklystreakgrant',name='member',field=models.ForeignKey(null=True,on_delete=django.db.models.deletion.SET_NULL,to='club.teammembership')),
        migrations.AddConstraint(model_name='weeklystreakgrant',constraint=models.UniqueConstraint(fields=['team','user','week_start','days'],name='unique_user_team_weekly_grant')),
        migrations.AddField(model_name='contestparticipation',name='hydrated_token',field=models.UUIDField(null=True)),
    ]
