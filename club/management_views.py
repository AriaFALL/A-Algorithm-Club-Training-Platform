from functools import wraps
import math
from datetime import datetime, timedelta

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.db.models import Q, Count, Sum, F
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.core.paginator import Paginator
from django.utils import timezone
from django.http import JsonResponse

from .models import Team, TeamMembership, Semester, Submission, SemesterMemberTotal, SubmissionPart, FileDeletion, ReviewLog, CleanupJob, ParserSettings, Problem
from .views import api_login_required, api_error, body, membership_for
from .currency_config import config_data, validate_config, apply_config


def administrator_required(view):
    @api_login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_superuser:
            return api_error('仅管理员可以执行此操作', 403)
        return view(request, *args, **kwargs)
    return wrapped


def title_manager_required(view):
    @api_login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        viewer = membership_for(request)
        if not request.user.is_superuser and (not viewer or not viewer.is_admin):
            return api_error('需要当前团队的题名处理权限', 403)
        request.title_team_id = None if request.user.is_superuser else viewer.team_id
        return view(request, *args, **kwargs)
    return wrapped


def title_scope(request):
    problems = Problem.objects.all()
    if request.title_team_id is not None:
        problems = problems.filter(submissions__team_id=request.title_team_id).distinct()
    return problems


@api_login_required
def workspace(request):
    if request.method != 'GET':
        return api_error('仅支持GET', 405)
    viewer = membership_for(request)
    if not request.user.is_superuser and (not viewer or not viewer.is_admin):
        return api_error('当前团队不在你的管理范围内，请切换到所管理的团队', 403)
    query = request.GET.get('q', '').strip()[:100]
    users = User.objects.filter(is_superuser=False).filter(Q(username__icontains=query) | Q(team_memberships__display_name__icontains=query)).distinct().order_by('username')[:200]
    teams = []
    scope = Team.objects.order_by('id') if request.user.is_superuser else Team.objects.filter(pk=viewer.team_id)
    for team in scope:
        managers = team.memberships.filter(role='admin', is_active=True, user__is_superuser=False).select_related('user')
        members = team.memberships.filter(is_active=True, user__is_superuser=False).select_related('user').order_by('display_name', 'id')
        counts = dict(Submission.objects.filter(member__in=members, is_valid=True, semester__archived_at__isnull=True).values('member_id').annotate(n=Count('id')).values_list('member_id', 'n'))
        archives = dict(SemesterMemberTotal.objects.filter(member__in=members, semester__archived_at__isnull=False).values('member_id').annotate(n=Sum('total_submissions')).values_list('member_id', 'n'))
        rows = [{'id': m.pk, 'user_id': m.user_id, 'account': m.user.username, 'name': m.display_name, 'role': m.role,
                 'submissions': counts.get(m.pk, 0) + archives.get(m.pk, 0),
                 'can_kick': m.user_id != request.user.pk and (request.user.is_superuser or m.role == 'member')} for m in members]
        teams.append({'id': team.pk, 'name': team.name, 'code': team.code,
            'members': len(rows), 'member_rows': rows,
            'managers': [{'id': m.user_id, 'account': m.user.username, 'name': m.display_name} for m in managers]})
    return JsonResponse({'site_admin': request.user.is_superuser, 'teams': teams, 'users': [{'id': u.pk, 'account': u.username,
        'group': '团队管理用户组' if u.team_memberships.filter(role='admin', is_active=True).exists() else '普通用户组'} for u in users] if request.user.is_superuser else []})


@administrator_required
@transaction.atomic
def assign_manager(request):
    if request.method != 'POST':
        return api_error('仅支持POST', 405)
    data = body(request)
    if type(data.get('team_id')) is not int or data.get('role') not in {'admin', 'member'}:
        return api_error('团队或角色无效')
    team = Team.objects.filter(pk=data['team_id']).first()
    user = User.objects.select_for_update().filter(username=str(data.get('account', '')).strip(), is_superuser=False, is_active=True).first()
    if not team or not user:
        return api_error('团队或普通用户账号不存在', 404)
    membership = TeamMembership.objects.filter(team=team, user=user).first()
    if data['role'] == 'member' and membership and not membership.is_active:
        return api_error('该成员已移出团队，请刷新', 409)
    if not membership:
        if data['role'] == 'member':
            return api_error('该账号不是此团队的管理用户')
        name = user.username[:40]
        if TeamMembership.objects.filter(team=team, display_name=name).exists():
            name = f'{name[:28]}#{user.pk}'
        membership = TeamMembership(user=user, team=team, display_name=name)
    membership.role = data['role']
    membership.is_active = True
    membership.save()
    return JsonResponse({'ok': True})


@transaction.atomic
def delete_team_data(team):
    # Match scoring/archive lock order before deleting the related rows.
    list(Semester.objects.select_for_update().filter(team=team).order_by('pk'))
    list(TeamMembership.objects.select_for_update().filter(team=team).order_by('pk'))
    from .models import ShopItem,ContestSubmission,Purchase,UserInventory
    names = set(SubmissionPart.objects.filter(submission__team=team).exclude(upload='').values_list('upload', flat=True))
    for pending in CleanupJob.objects.filter(semester__team=team).values_list('pending_files', flat=True):
        names.update(pending)
    names.update(ShopItem.objects.filter(team=team).exclude(icon='').values_list('icon',flat=True))
    names.update(ContestSubmission.objects.filter(team=team).exclude(screenshot='').values_list('screenshot',flat=True))
    if team.currency_icon:names.add(team.currency_icon.name)
    FileDeletion.objects.bulk_create([FileDeletion(name=name) for name in names if name])
    ReviewLog.objects.filter(submission__team=team).delete()
    # Explicit whole-team deletion removes team-owned purchase/inventory rows
    # before their PROTECT references to shop items are collected.
    UserInventory.objects.filter(team=team).delete()
    Purchase.objects.filter(team=team).delete()
    team.delete()


@administrator_required
def delete_team(request, team_id):
    if request.method != 'DELETE':
        return api_error('仅支持DELETE', 405)
    team = Team.objects.filter(pk=team_id).first()
    if not team:
        return api_error('团队不存在', 404)
    if body(request).get('confirmation') != team.code:
        return api_error('请输入正确团队码确认删除')
    delete_team_data(team)
    if request.session.get('team_id') == team_id:
        request.session.pop('team_id', None)
    return JsonResponse({'ok': True})


@api_login_required
@transaction.atomic
def kick_member(request, team_id, member_id):
    if request.method != 'DELETE':
        return api_error('仅支持DELETE', 405)
    viewer = membership_for(request)
    if not request.user.is_superuser and (not viewer or not viewer.is_admin or viewer.team_id != team_id):
        return api_error('无权管理此团队成员', 403)
    target = TeamMembership.objects.filter(pk=member_id, team_id=team_id).first()
    if not target:
        return api_error('成员不存在', 404)
    User.objects.select_for_update().get(pk=target.user_id)
    target = TeamMembership.objects.select_for_update().select_related('user').filter(pk=member_id).first()
    if not target:
        return api_error('成员已不存在，请刷新', 404)
    if target.user.is_superuser or target.user_id == request.user.pk or (not request.user.is_superuser and target.role != 'member'):
        return api_error('不能移出本人、系统管理员或由系统管理员设立的其他团队管理员', 403)
    if not target.is_active:
        return api_error('该成员已被移出', 409)
    if body(request).get('confirmation') != target.display_name:
        return api_error('成员信息已变化，请刷新后重试', 409)
    target.is_active = False
    target.role = 'member'
    target.save(update_fields=['is_active', 'role'])
    return JsonResponse({'ok': True})


@administrator_required
def platform_query_settings(request):
    from .problem_parser import key_cipher
    config = ParserSettings.objects.get_or_create(pk=1)[0]
    if request.method == 'GET':
        return JsonResponse({'has_luogu_cookie': bool(config.encrypted_luogu_cookie)})
    if request.method != 'PUT':
        return api_error('仅支持 GET 或 PUT', 405)
    data = body(request)
    cookie = data.get('cookie')
    if not isinstance(cookie,str) or len(cookie)>8192 or '\r' in cookie or '\n' in cookie:
        return api_error('Cookie 最多 8192 字符且不能含换行',400)
    pairs = dict(p.strip().split('=',1) for p in cookie.split(';') if '=' in p)
    if cookie.strip() and (not pairs.get('_uid','').isdigit() or not pairs.get('__client_id')):
        return api_error('请填写包含 _uid 和 __client_id 的洛谷 Cookie',400)
    config.encrypted_luogu_cookie = key_cipher().encrypt(cookie.strip().encode()).decode() if cookie.strip() else ''
    config.save(update_fields=['encrypted_luogu_cookie'])
    return JsonResponse({'has_luogu_cookie':bool(config.encrypted_luogu_cookie)})


@administrator_required
def parser_settings(request):
    from .problem_parser import key_cipher
    config = ParserSettings.objects.get_or_create(pk=1)[0]
    if request.method == 'GET':
        return JsonResponse({'mode': config.mode, 'enabled': config.enabled, 'base_url': config.base_url,
                             'model': config.model, 'api_protocol': config.api_protocol, 'has_key': bool(config.encrypted_key)})
    if request.method != 'PUT':
        return api_error('仅支持GET或PUT', 405)
    data = body(request)
    if data.get('mode') not in dict(ParserSettings.MODES) or type(data.get('enabled')) is not bool:
        return api_error('解析模式或AI开关无效')
    protocol = data.get('api_protocol', config.api_protocol)
    if protocol not in {'chat', 'responses'}:
        return api_error('调用协议无效')
    base_url, model, key = [str(data.get(k, '')).strip() for k in ('base_url', 'model', 'api_key')]
    if len(base_url) > 500 or len(model) > 200 or len(key) > 4096 or type(data.get('clear_key', False)) is not bool:
        return api_error('配置内容长度或格式无效')
    if base_url:
        from urllib.parse import urlsplit
        try:
            URLValidator(schemes=['http', 'https'])(base_url)
            parsed = urlsplit(base_url)
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValidationError('API地址不能包含凭据、查询参数或片段')
        except (ValidationError, ValueError):
            return api_error('请填写有效的HTTP/HTTPS API Base URL')
    config.api_protocol = protocol
    config.mode, config.enabled, config.base_url, config.model = data['mode'], data['enabled'], base_url, model
    if key:
        config.encrypted_key = key_cipher().encrypt(key.encode()).decode()
    elif data.get('clear_key'):
        config.encrypted_key = ''
    config.save()
    return JsonResponse({'ok': True, 'has_key': bool(config.encrypted_key)})


@administrator_required
def test_parser(request):
    if request.method != 'POST':
        return api_error('仅支持POST', 405)
    from .problem_parser import ai_title
    try:
        title = ai_title('https://www.nowcoder.com/practice/d53b2057ae8a4eaf8155447f6b709361', allow_unresolved=True)
    except ValueError as exc:
        return api_error(str(exc))
    return JsonResponse({'ok': True, 'title': title, 'warning': '' if title else '连接成功，但模型未能确认样例题名。请确认该服务与模型支持联网读取网页。'})


@title_manager_required
def problem_queue(request):
    if request.method != 'GET':
        return api_error('仅支持GET', 405)
    try:
        number = int(request.GET.get('page', '1'))
        if number < 1:
            raise ValueError()
    except ValueError:
        return api_error('页码无效')
    page = Paginator(title_scope(request).filter(status__in=['pending', 'running', 'failed']).order_by('requested_at', 'id'), 20).get_page(number)
    return JsonResponse({'problems': [{'id': p.pk, 'url': p.url, 'title': p.title, 'status': p.status,
        'mode': p.mode, 'error': p.error, 'requested_at': p.requested_at.isoformat() if p.requested_at else None} for p in page],
        'next': page.next_page_number() if page.has_next() else None})


@title_manager_required
def update_problem(request, problem_id):
    if request.method == 'DELETE':
        if not title_scope(request).filter(pk=problem_id, status__in=['pending', 'running', 'failed']).update(status='cancelled', error='', generation=F('generation') + 1):
            return api_error('任务不存在或已处理', 404)
        return JsonResponse({'ok': True})
    if request.method != 'PATCH':
        return api_error('仅支持PATCH', 405)
    title = body(request).get('title')
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 200:
        return api_error('题目名称需为1至200字')
    if not title_scope(request).filter(pk=problem_id).update(title=title.strip(), status='manual', error='', generation=F('generation') + 1):
        return api_error('题目不存在', 404)
    return JsonResponse({'ok': True})


@title_manager_required
def retry_problem(request, problem_id):
    if request.method != 'POST':
        return api_error('仅支持POST', 405)
    problem = title_scope(request).filter(pk=problem_id).first()
    if not problem:
        return api_error('题目不存在', 404)
    mode = body(request).get('mode')
    if mode not in dict(ParserSettings.MODES):
        return api_error('解析模式无效')
    from .problem_parser import enqueue_problem
    enqueue_problem(problem, mode)
    return JsonResponse({'ok': True}, status=202)


@administrator_required
@transaction.atomic
def team_configuration(request, team_id):
    team = Team.objects.filter(pk=team_id).first()
    if not team:
        return api_error('团队不存在', 404)
    # Lock semesters before team rows, matching scoring/archive/deletion.
    semester = Semester.objects.select_for_update().filter(team=team, is_active=True, archived_at__isnull=True).first()
    team = Team.objects.select_for_update().get(pk=team_id)
    if request.method == 'GET':
        return JsonResponse({
            'name': team.name,
            'code': team.code,
            'cleanup': cleanup_schedule_data(semester),
            'semester': {k: getattr(semester, k) for k in ['name', 'min_submissions', 'min_score', 'require_both', 'screenshot_points', 'logic_points', 'blog_points']} if semester else None,
            **config_data(team)
        })
    if request.method != 'PUT':
        return api_error('仅支持GET或PUT', 405)
    data = body(request)
    name,code=[str(data.get(k,'')).strip() for k in ('name','code')]
    if not 1 <= len(name) <= 80 or not 1 <= len(code) <= 32:
        return api_error('团队名或团队码长度无效')
    if Team.objects.filter(code__iexact=code).exclude(pk=team_id).exists():
        return api_error('团队码已被使用')
    fields = ['min_submissions', 'min_score', 'screenshot_points', 'logic_points', 'blog_points']
    if semester and (any(type(data.get(k)) is not int or not 0 <= data[k] <= 100000 for k in fields) or type(data.get('require_both')) is not bool):
        return api_error('计分与达标规则无效')
    try:
        validate_config(data)
    except ValueError as exc:
        return api_error(str(exc))
    team.name, team.code = name, code
    team.save()
    if semester:
        for field in fields + ['require_both']:
            setattr(semester, field, data[field])
        semester.save()
        from .services import refresh_totals
        refresh_totals(semester)

    apply_config(team, data)
    return JsonResponse({'ok': True})


def cleanup_schedule_data(semester):
    if not semester or not semester.cleanup_at:
        return None
    now = timezone.now()
    return {'time': (semester.cleanup_at - timedelta(days=7)).isoformat(),
            'execute_at': semester.cleanup_at.isoformat(),
            'days_left': max(0, math.ceil((semester.cleanup_at - now).total_seconds() / 86400)),
            'in_grace_period': semester.cleanup_at - timedelta(days=7) <= now < semester.cleanup_at}


@administrator_required
@transaction.atomic
def team_cleanup_schedule(request, team_id):
    semester = Semester.objects.select_for_update().filter(team_id=team_id, is_active=True, archived_at__isnull=True).first()
    if not semester:
        return api_error('当前没有可设置清理时间的活动学期，或清理已执行', 409)
    if request.method == 'DELETE':
        semester.cleanup_at = None
        semester.save(update_fields=['cleanup_at'])
        CleanupJob.objects.filter(semester=semester).exclude(status='completed').delete()
        return JsonResponse({'ok': True, 'cleanup': None})
    if request.method != 'POST':
        return api_error('仅支持 POST 或 DELETE', 405)
    if semester.cleanup_at:
        return api_error('请先撤销当前计划，再重新设置清理时间', 409)
    from django.utils.dateparse import parse_datetime
    try:
        value = body(request).get('cleanup_time')
        selected = parse_datetime(value) if isinstance(value, str) else None
        if selected and timezone.is_naive(selected):
            selected = timezone.make_aware(selected)
        if not selected or selected < timezone.now().replace(second=0, microsecond=0):
            return api_error('请选择当前或未来的清理时间')
    except (ValueError, TypeError, OverflowError):
        return api_error('清理时间格式无效')
    semester.cleanup_at = selected + timedelta(days=7)
    semester.save(update_fields=['cleanup_at'])
    CleanupJob.objects.update_or_create(semester=semester, defaults={'scheduled_for': semester.cleanup_at, 'status':'scheduled', 'error':''})
    return JsonResponse({'ok': True, 'cleanup': cleanup_schedule_data(semester)})
