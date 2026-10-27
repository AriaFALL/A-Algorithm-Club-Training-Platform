from datetime import timedelta

from celery import shared_task
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from .models import CleanupJob, Semester, FileDeletion, Problem
from django.core.files.storage import default_storage
from .services import build_weeks, cleanup_semester, settle_week, validate_week_dates


@shared_task
def settle_and_cleanup():
    now = timezone.now()
    purge_files()
    Problem.objects.filter(status__in=['pending', 'running'], requested_at__lt=now - timedelta(minutes=10)).update(status='failed', error='任务超时，请手动重新解析')
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
    job = CleanupJob.objects.select_related('semester').filter(pk=job_id).first()
    if not job:
        return {'status':'cancelled'}
    result = cleanup_semester(job.semester, enforce_schedule=True)
    if result is None:
        return {'status':'cancelled'}
    deleted, files = result
    return {'status': 'completed', 'deleted': deleted, 'files': files}


@shared_task
def resolve_problem(problem_id, generation, mode):
    from .problem_parser import resolve
    resolve(problem_id, generation, mode)


@shared_task
def purge_files():
    for entry in FileDeletion.objects.order_by('pk')[:500]:
        try:
            default_storage.delete(entry.name)
            entry.delete()
        except Exception:
            FileDeletion.objects.filter(pk=entry.pk).update(error='文件删除失败，等待重试')
