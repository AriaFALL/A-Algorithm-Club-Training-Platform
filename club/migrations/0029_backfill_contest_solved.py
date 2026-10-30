from django.db import migrations


def backfill(apps, schema_editor):
    Progress = apps.get_model('club', 'ContestProblemProgress')
    Binding = apps.get_model('club', 'PlatformBinding')
    Credit = apps.get_model('club', 'SolvedProblemCredit')
    db = schema_editor.connection.alias
    bindings = set(Binding.objects.using(db).values_list('user_id', 'platform', 'account'))
    for problem in Progress.objects.using(db).filter(accepted=True).select_related('participation').iterator():
        contest = problem.participation
        if contest.source_data.get('demo') or (contest.user_id, contest.platform, contest.account) not in bindings:
            continue
        Credit.objects.using(db).get_or_create(user_id=contest.user_id, source='contest',
            problem_key=f'{contest.platform}:{contest.contest_key}:{problem.problem_key}')


class Migration(migrations.Migration):
    dependencies = [('club', '0028_lifetime_solved_credits')]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
