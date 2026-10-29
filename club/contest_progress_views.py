import uuid
from datetime import timedelta
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from .views import api_login_required, api_error, membership_for, body
from .models import ContestParticipation, ContestSyncState, PlatformBinding, ContestProblemClaim, UserProfile
from .contest_rewards import serialize_participation, claim_problems


def enqueue(user_id, token):
    from .tasks import discover_contest_progress
    try:
        discover_contest_progress.delay(user_id, token)
    except Exception:
        ContestSyncState.objects.filter(user_id=user_id, token=token).update(
            status='failed', messages={'system':'同步服务暂不可用，请稍后重试'})


@api_login_required
@require_http_methods(['GET', 'POST'])
def progress(request):
    member = membership_for(request)
    if not member or not member.pk or request.user.is_superuser:
        return api_error('比赛进度仅供团队成员使用', 403)
    if request.method == 'POST':
        with transaction.atomic():
            state, _ = ContestSyncState.objects.select_for_update().get_or_create(user=request.user)
            if state.status == 'pending' and state.requested_at and (state.progressed_at or state.requested_at) > timezone.now()-timedelta(minutes=30):
                return JsonResponse({'status': 'pending'}, status=202)
            if not PlatformBinding.objects.filter(user=request.user).exists():
                return api_error('请先在个人信息页绑定竞赛平台账号', 400)
            state.token = uuid.uuid4(); state.status = 'pending'; state.requested_at = state.progressed_at = timezone.now()
            state.messages = {}; state.remaining = 0; state.total = 0; state.save()
            token = str(state.token)
            transaction.on_commit(lambda: enqueue(request.user.pk, token))
        return JsonResponse({'status': 'pending'}, status=202)
    state = ContestSyncState.objects.filter(user=request.user).first()
    rows = ContestParticipation.objects.filter(user=request.user).prefetch_related('problems').order_by('-starts_at')
    status = state.status if state else 'idle'
    last_progress=(state.progressed_at or state.requested_at) if state else None
    if state and status == 'pending' and (not last_progress or last_progress < timezone.now()-timedelta(minutes=30)):
        status = 'failed'
    claims = list(ContestProblemClaim.objects.filter(team=member.team).values('user_id','member_id','platform','account','contest_key','problem_key'))
    context = {'profile': UserProfile.objects.filter(user=request.user).first(),
               'bindings': set(PlatformBinding.objects.filter(user=request.user).values_list('platform','account')),
               'member_claims': {(c['platform'],c['contest_key'],c['problem_key']) for c in claims if c['user_id'] == member.user_id or c['member_id'] == member.pk},
               'account_claims': {(c['platform'],c['account'],c['contest_key'],c['problem_key']) for c in claims}}
    return JsonResponse({'contests': [serialize_participation(c, member, context) for c in rows],
                         'status': status, 'messages': state.messages if state else {},
                         'remaining': state.remaining if state else 0, 'total': state.total if state else 0})


@api_login_required
@require_http_methods(['POST'])
def claim(request):
    member = membership_for(request)
    if not member or not member.pk or request.user.is_superuser:
        return api_error('仅团队成员可以领取奖励', 403)
    data = body(request)
    ids = data.get('ids')
    if ids is not None and (not isinstance(ids, list) or not ids or len(ids) > 5000 or any(type(i) is not int for i in ids)):
        return api_error('题目编号无效', 400)
    try:
        return JsonResponse(claim_problems(member, ids))
    except ValueError as exc:
        return api_error(str(exc),400)
