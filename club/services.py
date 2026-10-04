from collections import defaultdict
from datetime import datetime, time, timedelta
from pathlib import Path

from django.db import models, transaction
from django.utils import timezone

from .models import ReviewLog, SemesterMemberTotal, Submission, SubmissionPart, Week


def score_part(part):
    points = {
        SubmissionPart.PROOF: part.submission.semester.screenshot_points,
        SubmissionPart.LOGIC: part.submission.semester.logic_points,
        SubmissionPart.BLOG: part.submission.semester.blog_points,
    }
    return points.get(part.kind, 0)


def submission_stats(week, member=None):
    queryset = Submission.objects.filter(week=week, is_valid=True)
    if member is not None:
        queryset = queryset.filter(member=member)
    submission_ids = queryset.values_list("id", flat=True)
    approved = SubmissionPart.objects.filter(submission_id__in=submission_ids, status=SubmissionPart.APPROVED)
    totals = defaultdict(int)
    for part in approved.select_related("submission"):
        totals[part.submission.member_id] += part.points_awarded
    counts = defaultdict(int)
    for submission_id, member_id in queryset.values_list("id", "member_id"):
        if SubmissionPart.objects.filter(submission_id=submission_id, kind=SubmissionPart.PROOF, status=SubmissionPart.APPROVED).exists():
            counts[member_id] += 1
    return totals, counts


@transaction.atomic
def approve_submission_parts(actor, part_ids=None, submission_ids=None, note=""):
    parts = SubmissionPart.objects.select_for_update().select_related("submission__semester", "submission__member").filter(status=SubmissionPart.PENDING)
    if part_ids:
        parts = parts.filter(id__in=part_ids)
    elif submission_ids:
        parts = parts.filter(submission_id__in=submission_ids)
    changed = 0
    for part in parts:
        if not part.has_content:
            continue
        part.status = SubmissionPart.APPROVED
        part.points_awarded = score_part(part)
        part.review_note = note
        part.reviewed_at = timezone.now()
        part.reviewed_by = actor
        part.save(update_fields=["status", "points_awarded", "review_note", "reviewed_at", "reviewed_by"])
        ReviewLog.objects.create(submission=part.submission, part=part, actor=actor, action="approve", detail={"points": part.points_awarded, "note": note})
        changed += 1
    return changed


def build_weeks(semester):
    existing = {week.number: week for week in semester.weeks.all()}
    current = semester.starts_on
    while current.weekday() != 6:
        current -= timedelta(days=1)
    number = 1
    while current <= semester.ends_on:
        start = timezone.make_aware(datetime.combine(current, time.min))
        end = start + timedelta(days=7)
        if number not in existing:
            existing[number] = Week.objects.create(semester=semester, number=number, starts_at=start, ends_at=end)
        current += timedelta(days=7)
        number += 1
    return list(sorted(existing.values(), key=lambda week: week.number))


def cleanup_semester(semester):
    from django.db.models import Sum

    members = semester.team.memberships.filter(is_active=True)
    for member in members:
        approved_points = SubmissionPart.objects.filter(submission__semester=semester, submission__member=member, status=SubmissionPart.APPROVED).aggregate(total=Sum("points_awarded"))["total"] or 0
        valid_submissions = Submission.objects.filter(semester=semester, member=member, is_valid=True).count()
        SemesterMemberTotal.objects.update_or_create(semester=semester, member=member, defaults={"total_score": approved_points, "total_submissions": valid_submissions})
    files = []
    for part in SubmissionPart.objects.filter(submission__semester=semester).only("upload"):
        if part.upload:
            files.append(part.upload.path)
    deleted, _ = Submission.objects.filter(semester=semester).delete()
    deleted_files = 0
    for path in files:
        try:
            Path(path).unlink(missing_ok=True)
            deleted_files += 1
        except OSError:
            pass
    semester.is_active = False
    semester.save(update_fields=["is_active"])
    return deleted, deleted_files


@transaction.atomic
def settle_week(week):
    """Close a finished week and refresh durable semester totals."""
    week.is_closed = True
    week.settled_at = timezone.now()
    week.save(update_fields=["is_closed", "settled_at"])
    semester = week.semester
    for member in semester.team.memberships.filter(is_active=True):
        score = SubmissionPart.objects.filter(submission__member=member, submission__semester=semester, submission__week=week, submission__is_valid=True, status=SubmissionPart.APPROVED).aggregate(total=models.Sum("points_awarded"))["total"] or 0
        count = Submission.objects.filter(member=member, semester=semester, week=week, is_valid=True, parts__kind=SubmissionPart.PROOF, parts__status=SubmissionPart.APPROVED).distinct().count()
        total_score = SubmissionPart.objects.filter(submission__member=member, submission__semester=semester, submission__is_valid=True, status=SubmissionPart.APPROVED).aggregate(total=models.Sum("points_awarded"))["total"] or 0
        total_submissions = Submission.objects.filter(member=member, semester=semester, is_valid=True, parts__kind=SubmissionPart.PROOF, parts__status=SubmissionPart.APPROVED).distinct().count()
        qualified_weeks = 0
        for closed_week in semester.weeks.filter(is_closed=True):
            closed_score = SubmissionPart.objects.filter(submission__member=member, submission__week=closed_week, submission__is_valid=True, status=SubmissionPart.APPROVED).aggregate(total=models.Sum("points_awarded"))["total"] or 0
            closed_count = Submission.objects.filter(member=member, week=closed_week, is_valid=True, parts__kind=SubmissionPart.PROOF, parts__status=SubmissionPart.APPROVED).distinct().count()
            qualified = (closed_count >= closed_week.effective_min_submissions and closed_score >= closed_week.effective_min_score) if closed_week.effective_require_both else (closed_count >= closed_week.effective_min_submissions or closed_score >= closed_week.effective_min_score)
            qualified_weeks += int(qualified)
        SemesterMemberTotal.objects.update_or_create(semester=semester, member=member, defaults={"total_score": total_score, "total_submissions": total_submissions, "qualified_weeks": qualified_weeks})
    return week
