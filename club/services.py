from collections import defaultdict
from datetime import datetime, time, timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.storage import default_storage
from django.db import models, transaction
from django.utils import timezone

from .models import CleanupJob, ReviewLog, Semester, SemesterMemberTotal, Submission, SubmissionPart, TeamMembership, Week


def score_part(part):
    semester = part.submission.semester
    return {SubmissionPart.PROOF: semester.screenshot_points, SubmissionPart.LOGIC: semester.logic_points, SubmissionPart.BLOG: semester.blog_points}.get(part.kind, 0)


def progress_rows(semester, week=None, member_ids=None, submission_ids=None):
    """One definition of approved scores and accepted proof counts."""
    submissions = Submission.objects.filter(semester=semester, is_valid=True)
    if week is not None:
        submissions = submissions.filter(week=week)
    if member_ids is not None:
        submissions = submissions.filter(member_id__in=member_ids)
    if submission_ids is not None:
        submissions = submissions.filter(pk__in=submission_ids)
    scores = dict(SubmissionPart.objects.filter(submission__in=submissions, status=SubmissionPart.APPROVED)
                  .values('submission__member_id').annotate(total=models.Sum('points_awarded'))
                  .values_list('submission__member_id', 'total'))
    counts = dict(submissions.filter(parts__kind=SubmissionPart.PROOF, parts__status=SubmissionPart.APPROVED)
                  .values('member_id').annotate(total=models.Count('id', distinct=True)).values_list('member_id', 'total'))
    return scores, counts


def qualified(score, count, week):
    checks = (count >= week.effective_min_submissions, score >= week.effective_min_score)
    return all(checks) if week.effective_require_both else any(checks)


def submission_stats(week, member=None):
    scores, counts = progress_rows(week.semester, week, [member.id] if member else None)
    return defaultdict(int, scores), defaultdict(int, counts)


def refresh_totals(semester):
    """Caller holds the semester lock, shared by review, settlement and archive."""
    if semester.archived_at:
        return
    scores, counts = progress_rows(semester)
    qualified_counts = defaultdict(int)
    members = list(semester.team.memberships.all())
    for week in semester.weeks.filter(is_closed=True):
        week_scores, week_counts = progress_rows(semester, week)
        for member in members:
            qualified_counts[member.id] += int(qualified(week_scores.get(member.id, 0), week_counts.get(member.id, 0), week))
    # The caller's semester lock serializes this upsert with reviews and archive.
    SemesterMemberTotal.objects.bulk_create([
        SemesterMemberTotal(
            semester=semester, member=member, display_name=member.display_name,
            total_score=scores.get(member.id, 0), total_submissions=counts.get(member.id, 0),
            qualified_weeks=qualified_counts[member.id],
        ) for member in members
    ], update_conflicts=True, unique_fields=['semester', 'member'],
       update_fields=['display_name', 'total_score', 'total_submissions', 'qualified_weeks', 'finalized_at'])


def normalize_ids(values):
    if not isinstance(values, list) or not values or len(values) > 1000:
        raise ValidationError('请选择 1 至 1000 个有效编号')
    if any(type(value) is not int or value <= 0 for value in values):
        raise ValidationError('编号必须为正整数')
    return set(values)


@transaction.atomic
def review_submission_parts(actor, team, *, part_ids=None, submission_ids=None, action='approve', note=''):
    if not TeamMembership.objects.filter(user=actor, team=team, is_active=True, role__in=['admin', 'owner']).exists():
        raise PermissionDenied('需要当前团队管理员权限')
    if action not in {'approve', 'reject'}:
        raise ValidationError('审核操作无效')
    if part_ids is not None and submission_ids is not None:
        raise ValidationError('请只指定一种编号')
    ids = normalize_ids(part_ids if part_ids is not None else submission_ids)
    targets = SubmissionPart.objects.filter(submission__team=team)
    if part_ids is not None:
        targets = targets.filter(pk__in=ids)
        found = set(targets.values_list('id', flat=True))
    else:
        submissions = Submission.objects.filter(team=team, pk__in=ids)
        found = set(submissions.values_list('id', flat=True))
        targets = targets.filter(submission_id__in=ids)
    if found != ids or not targets.exists():
        raise ValidationError('所选材料不存在或不属于当前团队')
    semester_ids = set(targets.values_list('submission__semester_id', flat=True))
    semesters = list(Semester.objects.select_for_update().filter(pk__in=semester_ids).order_by('pk'))
    if any(semester.archived_at for semester in semesters):
        raise ValidationError('学期已归档，不能继续审核')
    # Recheck after acquiring locks: cleanup could have removed the targets.
    if not targets.exists():
        raise ValidationError('材料已清理，请刷新页面')
    changed = 0
    for part in targets.select_for_update(of=('self',)).select_related('submission__semester').filter(status=SubmissionPart.PENDING):
        if not part.has_content:
            continue
        part.status = SubmissionPart.APPROVED if action == 'approve' else SubmissionPart.REJECTED
        part.points_awarded = score_part(part) if action == 'approve' else 0
        part.review_note = str(note)[:500]
        part.reviewed_at = timezone.now()
        part.reviewed_by = actor
        part.save(update_fields=['status', 'points_awarded', 'review_note', 'reviewed_at', 'reviewed_by'])
        ReviewLog.objects.create(submission=part.submission, part=part, actor=actor, action=action,
                                 detail={'points': part.points_awarded, 'note': part.review_note})
        changed += 1
    for semester in semesters:
        refresh_totals(semester)
    return changed


def approve_submission_parts(actor, team, part_ids=None, submission_ids=None, note=''):
    return review_submission_parts(actor, team, part_ids=part_ids, submission_ids=submission_ids, note=note)


def week_bounds(semester, number):
    monday = semester.starts_on - timedelta(days=semester.starts_on.weekday())
    start = timezone.make_aware(datetime.combine(monday + timedelta(weeks=number - 1), time.min))
    return start, start + timedelta(days=7)


def validate_week_dates(semester):
    if any((week.starts_at, week.ends_at) != week_bounds(semester, week.number) for week in semester.weeks.all()):
        raise ValidationError('周次日期异常，请先运行 repair_weeks 检查并修复')


def build_weeks(semester):
    """Create missing weeks only; never silently rewrite historical records."""
    weeks = list(semester.weeks.order_by('number'))
    existing_numbers = {week.number for week in weeks}
    missing = []
    number = 1
    start, end = week_bounds(semester, number)
    while timezone.localdate(start) <= semester.ends_on:
        if number not in existing_numbers:
            missing.append(Week(semester=semester, number=number, starts_at=start, ends_at=end))
        number += 1
        start, end = week_bounds(semester, number)
    if missing:
        # Concurrent page loads can discover the same missing weeks.
        Week.objects.bulk_create(missing, ignore_conflicts=True)
        return list(semester.weeks.order_by('number'))
    return weeks


@transaction.atomic
def settle_week(week):
    semester = Semester.objects.select_for_update().get(pk=week.semester_id)
    if semester.archived_at:
        return week
    validate_week_dates(semester)
    Week.objects.filter(pk=week.pk).update(is_closed=True, settled_at=timezone.now())
    refresh_totals(semester)
    week.refresh_from_db()
    return week


def cleanup_semester(semester):
    """Commit archive + file manifest before deletion; retries keep the snapshot."""
    with transaction.atomic():
        semester = Semester.objects.select_for_update().get(pk=semester.pk)
        job, _ = CleanupJob.objects.get_or_create(semester=semester, defaults={'scheduled_for': semester.cleanup_at or timezone.now()})
        if job.status == 'completed':
            return job.deleted_submissions, job.deleted_files
        if not semester.archived_at:
            validate_week_dates(semester)
            semester.weeks.filter(ends_at__lte=timezone.now(), is_closed=False).update(is_closed=True, settled_at=timezone.now())
            refresh_totals(semester)
            job.pending_files = list(SubmissionPart.objects.filter(submission__semester=semester).exclude(upload='').values_list('upload', flat=True).distinct())
            job.deleted_submissions = semester.submissions.count()
            job.save(update_fields=['pending_files', 'deleted_submissions'])
            semester.archived_at = timezone.now()
            semester.is_active = False
            semester.save(update_fields=['archived_at', 'is_active'])
            ReviewLog.objects.filter(submission__semester=semester).delete()
            semester.submissions.all().delete()
        job.status = 'running'
        job.started_at = timezone.now()
        job.error = ''
        job.save(update_fields=['status', 'started_at', 'error'])
    try:
        # Keep the manifest until ALL files have been removed. Missing files are safe on retry.
        for name in job.pending_files:
            default_storage.delete(name)
        with transaction.atomic():
            Semester.objects.select_for_update().get(pk=semester.pk)
            job.refresh_from_db()
            if job.status != 'completed':
                job.deleted_files = len(job.pending_files)
                job.pending_files = []
                job.status = 'completed'
                job.finished_at = timezone.now()
                job.error = ''
                job.save(update_fields=['deleted_files', 'pending_files', 'status', 'finished_at', 'error'])
        return job.deleted_submissions, job.deleted_files
    except Exception as exc:
        CleanupJob.objects.filter(pk=job.pk).exclude(status='completed').update(status='failed', error=str(exc)[:2000])
        raise
