from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Max
from django.http import JsonResponse
from django.utils import timezone

from .models import Problem, ReviewLog, Semester, Submission, SubmissionLike, SubmissionPart, SubmissionReport, Week
from .services import refresh_totals
from .views import api_error, api_login_required, membership_for, active_semester, active_week, serialize_submission, body


def page_items(request, queryset, size=20):
    try:
        number = int(request.GET.get('page', '1'))
        if number < 1:
            raise ValueError()
    except ValueError:
        return None
    pager = Paginator(queryset, size)
    page = pager.get_page(number)
    return page


@api_login_required
def showcase(request):
    if request.method != 'GET':
        return api_error('仅支持GET', 405)
    member = membership_for(request)
    if not member:
        return api_error('未加入当前团队', 403)
    weeks = Week.objects.filter(semester__team=member.team, semester__archived_at__isnull=True).select_related('semester').order_by('-starts_at')
    selected = request.GET.get('week')
    semester = active_semester(member.team)
    if selected:
        if not selected.isdigit():
            return api_error('周次编号无效')
        week = weeks.filter(pk=selected).first()
        if not week:
            return api_error('周次不存在', 404)
    else:
        week = active_week(semester) if semester else None
    items = Submission.objects.filter(team=member.team, week=week, is_valid=True, semester__archived_at__isnull=True, problem__isnull=False)
    grouped = items.values('problem_id', 'problem__url', 'problem__title').annotate(count=Count('id'), latest=Max('submitted_at')).order_by('-latest', '-problem_id')
    page = page_items(request, grouped)
    if page is None:
        return api_error('页码无效')
    groups = list(page.object_list)
    names = {}
    for pid, name in items.filter(problem_id__in=[g['problem_id'] for g in groups]).values_list('problem_id', 'member__display_name').distinct():
        names.setdefault(pid, []).append(name)
    return JsonResponse({'week': week.pk if week else None,
        'weeks': [{'id': w.pk, 'label': f'{w.semester.name} · 第{w.number}周'} for w in weeks],
        'problems': [{'id': g['problem_id'], 'title': g['problem__title'] or g['problem__url'], 'url': g['problem__url'], 'count': g['count'], 'members': sorted(names.get(g['problem_id'], []))} for g in groups],
        'next': page.next_page_number() if page.has_next() else None})


def community_submission(item, viewer):
    data = serialize_submission(item)
    data.update(likes=item.likes.count(), liked=item.likes.filter(user=viewer.user).exists(),
                reported=item.reports.filter(version=item.version, reporter=viewer.user).exists(),
                own=item.member.user_id == viewer.user_id, can_reject=viewer.is_admin and item.member.user_id != viewer.user_id and not item.semester.archived_at, archived=bool(item.semester.archived_at))
    return data


@api_login_required
def problem_submissions(request, problem_id):
    if request.method != 'GET':
        return api_error('仅支持GET', 405)
    member = membership_for(request)
    if not member:
        return api_error('未加入当前团队', 403)
    items = Submission.objects.filter(team=member.team, problem_id=problem_id, is_valid=True, semester__archived_at__isnull=True).select_related('problem', 'member', 'week', 'semester').prefetch_related('parts', 'likes', 'reports').order_by('-submitted_at', '-id')
    if not items.exists():
        return api_error('该题目不存在或没有可见提交', 404)
    problem = items.first().problem
    page = page_items(request, items)
    if page is None:
        return api_error('页码无效')
    return JsonResponse({'problem': {'id': problem.pk, 'title': problem.title or problem.url, 'url': problem.url},
                         'submissions': [community_submission(s, member) for s in page],
                         'next': page.next_page_number() if page.has_next() else None})


@api_login_required
@transaction.atomic
def reaction(request, submission_id, kind):
    if request.method not in ({'PUT', 'DELETE'} if kind == 'like' else {'POST'}):
        return api_error('请求方法无效', 405)
    member = membership_for(request)
    if not member:
        return api_error('未加入当前团队', 403)
    target = Submission.objects.filter(pk=submission_id, team=member.team).first()
    if not target:
        return api_error('提交不存在', 404)
    semester = Semester.objects.select_for_update().get(pk=target.semester_id)
    target = Submission.objects.select_for_update().filter(pk=submission_id, is_valid=True).first()
    if not target or semester.archived_at:
        return api_error('提交已退回或归档', 409)
    if target.member_id == member.pk:
        return api_error('不能对自己的提交点赞或举报', 403)
    if kind == 'like':
        if request.method == 'PUT':
            SubmissionLike.objects.get_or_create(submission=target, user=request.user)
        else:
            target.likes.filter(user=request.user).delete()
        return JsonResponse({'ok': True, 'likes': target.likes.count(), 'liked': request.method == 'PUT'})
    SubmissionReport.objects.get_or_create(submission=target, version=target.version, reporter=request.user)
    return JsonResponse({'ok': True})


@api_login_required
def report_queue(request):
    member = membership_for(request)
    if not request.user.is_superuser and (not member or not member.is_admin):
        return api_error('需要当前团队管理权限', 403)
    if request.method != 'GET':
        return api_error('仅支持GET', 405)
    items = Submission.objects.filter(is_valid=True, semester__archived_at__isnull=True,
        reports__status='pending', reports__version=F('version'))
    if not request.user.is_superuser:
        items = items.filter(team=member.team)
    items = items.distinct().select_related('team', 'problem', 'member', 'week', 'semester').prefetch_related('parts').order_by('submitted_at', 'id')
    page = page_items(request, items)
    if page is None:
        return api_error('页码无效')
    rows = []
    for item in page:
        data = serialize_submission(item)
        data['team_name'] = item.team.name
        data['reports'] = item.reports.filter(status='pending', version=item.version).count()
        data['can_resolve'] = item.member.user_id != request.user.pk
        rows.append(data)
    return JsonResponse({'submissions': rows, 'next': page.next_page_number() if page.has_next() else None})


@api_login_required
@transaction.atomic
def resolve_report(request, submission_id, direct=False):
    if request.method != 'POST':
        return api_error('仅支持POST', 405)
    member = membership_for(request)
    if not request.user.is_superuser and (not member or not member.is_admin):
        return api_error('需要当前团队管理权限', 403)
    targets = Submission.objects.filter(pk=submission_id)
    if not request.user.is_superuser:
        targets = targets.filter(team=member.team)
    target = targets.first()
    if not target:
        return api_error('提交不存在', 404)
    semester = Semester.objects.select_for_update().get(pk=target.semester_id)
    target = Submission.objects.select_for_update().filter(pk=submission_id).first()
    if not target or semester.archived_at:
        return api_error('材料已清理或学期已归档', 409)
    if target.member.user_id == request.user.pk:
        return api_error('不能处理自己的提交', 403)
    if not target.is_valid:
        return api_error('该提交已退回', 409)
    data = body(request)
    if data.get('version') != target.version:
        return api_error('提交版本已变化，请刷新', 409)
    action = 'reject' if direct else data.get('action')
    note = str(data.get('note', '')).strip()
    if action not in {'dismiss', 'reject'} or (action == 'reject' and not note) or len(note) > 500:
        return api_error('请选择处理方式，退回理由为1至500字')
    reports = target.reports.filter(status='pending', version=target.version)
    if not direct and not reports.exists():
        return api_error('举报已处理，请刷新', 409)
    reports.update(status='rejected' if action == 'reject' else 'dismissed', resolved_by=request.user, resolved_at=timezone.now(), note=note)
    if action == 'reject':
        target.is_valid = False
        target.rejection_note = note
        target.save(update_fields=['is_valid', 'rejection_note'])
        target.parts.update(status='rejected', points_awarded=0, review_note=note, reviewed_at=timezone.now(), reviewed_by=request.user)
        refresh_totals(semester)
    ReviewLog.objects.create(submission=target, actor=request.user, action=('direct_' if direct else 'report_') + action, detail={'version': target.version, 'note': note})
    return JsonResponse({'ok': True})
