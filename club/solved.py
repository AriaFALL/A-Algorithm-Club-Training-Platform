"""Lifetime solved totals: durable contest ACs + archived/live approved problems."""
from collections import defaultdict
from .models import SolvedProblemCredit, Submission, SubmissionPart, PlatformBinding


def archive_submission_credits(semester):
    rows = Submission.objects.filter(semester=semester, is_valid=True, problem__isnull=False,
        parts__kind=SubmissionPart.PROOF, parts__status=SubmissionPart.APPROVED
    ).values_list('member__user_id', 'problem__identity').distinct()
    SolvedProblemCredit.objects.bulk_create([
        SolvedProblemCredit(user_id=uid, source='submission', problem_key=key) for uid, key in rows
    ], ignore_conflicts=True)


def remember_contest_ac(problem):
    contest = problem.participation
    if not problem.accepted or contest.source_data.get('demo'):
        return
    if not PlatformBinding.objects.filter(user_id=contest.user_id, platform=contest.platform, account=contest.account).exists():
        return
    SolvedProblemCredit.objects.get_or_create(user_id=contest.user_id, source='contest',
        problem_key=f'{contest.platform}:{contest.contest_key}:{problem.problem_key}')


def lifetime_solved_counts(user_ids):
    problems = defaultdict(set)
    for uid, source, key in SolvedProblemCredit.objects.filter(user_id__in=user_ids).values_list('user_id', 'source', 'problem_key'):
        problems[uid].add((source, key))
    for uid, key in Submission.objects.filter(member__user_id__in=user_ids, is_valid=True, problem__isnull=False,
        parts__kind=SubmissionPart.PROOF, parts__status=SubmissionPart.APPROVED
    ).values_list('member__user_id', 'problem__identity').distinct():
        problems[uid].add(('submission', key))
    return {uid: len(keys) for uid, keys in problems.items()}
