from datetime import timedelta

from celery import shared_task
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from .models import CleanupJob, Semester
from .services import build_weeks, cleanup_semester, settle_week, validate_week_dates


@shared_task
def settle_and_cleanup():
    now = timezone.now()
    blocked_semesters = []
    for semester in Semester.objects.filter(is_active=True, archived_at__isnull=True):
        build_weeks(semester)
        try:
            validate_week_dates(semester)
        except ValidationError:
            blocked_semesters.append(semester.pk)
            continue
        for week in semester.weeks.filter(ends_at__lte=now, is_closed=False):
            settle_week(week)
        if semester.cleanup_at and semester.cleanup_at <= now:
            CleanupJob.objects.get_or_create(semester=semester, defaults={'scheduled_for': semester.cleanup_at})
    retryable = Q(status__in=['scheduled', 'failed']) | Q(status='running', started_at__lt=now - timedelta(minutes=10))
    for job in CleanupJob.objects.filter(retryable, scheduled_for__lte=now):
        run_cleanup.delay(job.pk)
    return {'checked_at': now.isoformat(), 'needs_week_repair': blocked_semesters}


@shared_task
def run_cleanup(job_id):
    job = CleanupJob.objects.select_related('semester').get(pk=job_id)
    deleted, files = cleanup_semester(job.semester)
    return {'status': 'completed', 'deleted': deleted, 'files': files}
