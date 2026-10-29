import re
from datetime import timedelta
from zoneinfo import ZoneInfo
from django.db import migrations


def seed(apps, schema_editor):
    Transaction = apps.get_model('club', 'CurrencyTransaction')
    Grant = apps.get_model('club', 'WeeklyStreakGrant')
    for row in Transaction.objects.filter(transaction_type='streak_bonus').iterator():
        match = re.search(r'(\d+)\s*天', row.description)
        if match and 1 <= int(match[1]) <= 7:
            day = row.created_at.astimezone(ZoneInfo('Asia/Shanghai')).date()
            Grant.objects.get_or_create(member_id=row.member_id, week_start=day-timedelta(days=day.weekday()),
                                        days=int(match[1]), defaults={'amount': max(0,row.amount)})
    # Longer-than-week rules cannot fire under the new policy. Keep all valid
    # custom weekly rules and replace only the old built-in 30-day default.
    Rule = apps.get_model('club', 'StreakReward')
    for row in Rule.objects.filter(days=30, reward=5):
        Rule.objects.get_or_create(team_id=row.team_id, days=3, defaults={'reward': 1})
    Rule.objects.filter(days__gt=7).delete()


class Migration(migrations.Migration):
    dependencies = [('club', '0017_contest_progress')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
