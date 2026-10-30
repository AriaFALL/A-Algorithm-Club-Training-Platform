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
    from .semester_calendar import ensure_current_semester
    from .models import Team
    for team in Team.objects.filter(semesters__calendar_managed=True).distinct():
        ensure_current_semester(team)
    purge_files()
    Problem.objects.filter(status__in=['pending', 'running'], requested_at__lt=now - timedelta(minutes=10)).update(status='failed', error='任务超时，请手动重新解析')
    blocked_semesters = []
    for semester in Semester.objects.filter(Q(is_active=True) | Q(calendar_managed=True), archived_at__isnull=True):
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


@shared_task(soft_time_limit=155, time_limit=165, priority=2)
def sync_platform_binding(binding_id, token):
    from .models import PlatformBinding
    from .platform_sync import fetch_snapshot, SyncError
    binding = PlatformBinding.objects.filter(pk=binding_id, sync_token=token, status='pending').first()
    if not binding:
        return
    try:
        snapshot = fetch_snapshot(binding.platform, binding.account)
        PlatformBinding.objects.filter(pk=binding_id, sync_token=token).update(
            snapshot=snapshot, status='ready', error='', synced_at=timezone.now())
    except Exception as exc:
        # Do not expose credentials, URLs with user input, or response bodies.
        message = str(exc)[:240] if isinstance(exc, SyncError) else '平台数据读取失败，请稍后重试或检查账号与凭据'
        PlatformBinding.objects.filter(pk=binding_id, sync_token=token).update(status='failed', error=message)


@shared_task(soft_time_limit=750, time_limit=780)
def discover_contest_progress(user_id, token):
    from django.db import transaction
    from .models import ContestSyncState, ContestParticipation, PlatformBinding
    from .contest_progress_sources import discover, Remote, SyncError
    pending = []
    messages = {}
    for binding in PlatformBinding.objects.filter(user_id=user_id):
        remote = Remote()
        try:
            rows = discover(remote, binding.platform, binding.account)
            with transaction.atomic():
                state = ContestSyncState.objects.select_for_update().filter(user_id=user_id, token=token).first()
                if not state:
                    return
                if not PlatformBinding.objects.filter(pk=binding.pk, account=binding.account).exists():
                    continue
                state.progressed_at=timezone.now();state.save(update_fields=['progressed_at'])
                for row in rows:
                    key = row.pop('contest_key')
                    c, _ = ContestParticipation.objects.update_or_create(user_id=user_id, platform=binding.platform,
                        account=binding.account, contest_key=key, defaults=row)
                    pending.append(c.pk)
            messages[binding.platform] = f'已获取 {len(rows)} 场参赛记录'
        except Exception as exc:
            messages[binding.platform] = str(exc)[:240] if isinstance(exc, SyncError) else '比赛历史同步失败，保留已有记录'
        finally:
            remote.session.close()
    with transaction.atomic():
        state = ContestSyncState.objects.select_for_update().filter(user_id=user_id, token=token).first()
        if not state:
            return
        state.progressed_at=timezone.now()
        state.messages = messages; state.total = state.remaining = len(pending)
        state.status = 'pending' if pending else 'ready'; state.finished_at = None if pending else timezone.now(); state.save()
        for pk in pending:
            transaction.on_commit(lambda pk=pk: enqueue_hydration(pk, token))


def enqueue_hydration(contest_id, token):
    try:
        hydrate_contest_progress.apply_async(args=[contest_id,token],retry=False)
    except Exception:
        from .models import ContestSyncState,ContestParticipation
        contest=ContestParticipation.objects.filter(pk=contest_id).first()
        if contest:
            ContestSyncState.objects.filter(user_id=contest.user_id,token=token).update(
                status='failed',messages={'system':'比赛任务未能入队，请重新同步；已有进度已保留'})


@shared_task(soft_time_limit=155, time_limit=165)
def hydrate_contest_progress(contest_id, token):
    from django.db import transaction
    from .models import ContestSyncState, ContestParticipation, ContestProblemProgress, PlatformBinding
    from .contest_progress_sources import hydrate, Remote, SyncError
    c = ContestParticipation.objects.filter(pk=contest_id).first()
    if not c or str(c.hydrated_token)==str(token) or not ContestSyncState.objects.filter(user=c.user, token=token, status='pending').exists():
        return
    remote = Remote(); rows = None; error = ''
    try:
        rows, error = hydrate(remote, c)
    except Exception as exc:
        error = str(exc)[:240] if isinstance(exc, SyncError) else '比赛题目或正式榜单暂不可读取，请稍后同步'
    finally:
        remote.session.close()
    verified_ends_at=c.ends_at
    with transaction.atomic():
        state = ContestSyncState.objects.select_for_update().filter(user=c.user, token=token).first()
        if not state:
            return
        c = ContestParticipation.objects.select_for_update().get(pk=c.pk)
        if str(c.hydrated_token) == str(token):
            return
        c.hydrated_token = token
        c.save(update_fields=['hydrated_token'])
        if PlatformBinding.objects.filter(user=c.user, platform=c.platform, account=c.account).exists():
            if rows is not None and (not error or not c.detail_complete):
                c.ends_at=verified_ends_at
                keys = [row['problem_key'] for row in rows]
                for row in rows:
                    key = row.pop('problem_key')
                    ContestProblemProgress.objects.update_or_create(participation=c, problem_key=key, defaults=row)
                ContestProblemProgress.objects.filter(participation=c).exclude(problem_key__in=keys).delete()
                c.detail_complete = not bool(error)
            c.sync_error = error; c.save()
        state.progressed_at=timezone.now()
        state.remaining = max(0, state.remaining-1)
        if not state.remaining:
            state.status = 'ready'; state.finished_at = timezone.now()
        state.save()


@shared_task(priority=0)
def refresh_contest_calendar():
    from .contest_views import refresh_calendar
    snapshots = refresh_calendar(force=True)
    return {platform: {'updated_at': row['updated_at'], 'error': row['error']} for platform,row in snapshots.items()}
