from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .models import CleanupJob, ReviewLog, Semester, SemesterMemberTotal, Submission, SubmissionPart, Week
from .services import build_weeks, cleanup_semester, settle_week


@shared_task
def settle_and_cleanup():
    now = timezone.now()
    for semester in Semester.objects.filter(is_active=True):
        build_weeks(semester)
        for week in semester.weeks.filter(ends_at__lte=now, is_closed=False):
            settle_week(week)
        # 即使提交没有附件，也必须执行清理，避免仅保留文字的记录残留。
        if semester.cleanup_at and semester.cleanup_at <= now and Submission.objects.filter(semester=semester).exists():
            job, _ = CleanupJob.objects.get_or_create(semester=semester, defaults={"scheduled_for": semester.cleanup_at})
            if job.status not in {"running", "completed"}:
                run_cleanup.delay(job.id)
    return {"checked_at": now.isoformat()}


@shared_task
def run_cleanup(job_id):
    job = CleanupJob.objects.select_related("semester").get(id=job_id)
    if job.status == "completed":
        return {"status": "completed"}
    job.status = "running"
    job.started_at = timezone.now()
    job.save(update_fields=["status", "started_at"])
    try:
        deleted, files = cleanup_semester(job.semester)
        job.deleted_submissions = deleted
        job.deleted_files = files
        job.status = "completed"
        job.finished_at = timezone.now()
        job.save(update_fields=["deleted_submissions", "deleted_files", "status", "finished_at"])
        return {"status": job.status, "deleted": deleted, "files": files}
    except Exception as exc:
        job.status = "failed"
        job.error = str(exc)[:2000]
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error", "finished_at"])
        raise
