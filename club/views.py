import json
import io
import warnings
from urllib.parse import quote

from PIL import Image, UnidentifiedImageError
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.http import HttpResponse
from datetime import datetime, timedelta
from pathlib import Path

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.http import FileResponse, Http404, JsonResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from django.contrib.auth.hashers import check_password, make_password
from functools import wraps

from .models import Arena, ReviewLog, Semester, SemesterMemberTotal, Submission, SubmissionPart, Team, TeamMembership, Week, create_internal_username
from .services import build_weeks, review_submission_parts, normalize_ids, progress_rows, qualified, refresh_totals, week_bounds

BASE_DIR = Path(__file__).resolve().parent.parent


def api_error(message, status=400):
    return JsonResponse({"error": message}, status=status)


def api_login_required(view):
    """Return JSON 401 responses for API calls instead of HTML redirects."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return api_error("请先登录", 401)
        return view(request, *args, **kwargs)
    return wrapped


@ensure_csrf_cookie
def api_csrf(request):
    if request.method != "GET":
        return api_error("仅支持 GET", 405)
    response = JsonResponse({"csrfToken": get_token(request)})
    response["Cache-Control"] = "no-store"
    return response


def body(request):
    try:
        data = json.loads(request.body or "{}")
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def membership_for(request, team_id=None):
    if not request.user.is_authenticated:
        return None
    team_id = team_id or request.session.get("team_id")
    queryset = TeamMembership.objects.select_related("team").filter(user=request.user, is_active=True)
    membership = queryset.filter(team_id=team_id).first() if team_id else queryset.first()
    return membership


def active_semester(team):
    today = timezone.localdate()
    semester = team.semesters.filter(is_active=True, archived_at__isnull=True, starts_on__lte=today, ends_on__gte=today).first()
    if semester:
        build_weeks(semester)
    return semester


def active_week(semester):
    now = timezone.now()
    return semester.weeks.filter(starts_at__lte=now, ends_at__gt=now, is_closed=False).first()


def member_week_score(member, week):
    return progress_rows(week.semester, week, [member.id])[0].get(member.id, 0)


def member_week_submissions(member, week):
    return progress_rows(week.semester, week, [member.id])[1].get(member.id, 0)


def week_progress_qualified(score, submissions, week):
    return qualified(score, submissions, week)


def member_week_qualified(member, week):
    scores, counts = progress_rows(week.semester, week, [member.id])
    return qualified(scores.get(member.id, 0), counts.get(member.id, 0), week)


def member_week_progress(members, week):
    return progress_rows(week.semester, week, [member.id for member in members]) if week and members else ({}, {})


def leaderboard_rows_for(team, semester, week=None):
    scores, counts = progress_rows(semester, week)
    rows = [{'memberId': member.id, 'name': member.display_name, 'score': scores.get(member.id, 0),
             'submissions': counts.get(member.id, 0)} for member in team.memberships.filter(is_active=True)]
    rows.sort(key=lambda row: (-row['score'], -row['submissions'], row['name']))
    for index, row in enumerate(rows, 1):
        row['rank'] = index
    return rows


def member_streak(member, semester, through_week):
    weeks = list(semester.weeks.filter(number__lte=through_week.number).order_by("-number"))
    streak = 0
    for week in weeks:
        # The open week is still in progress and cannot be counted as a
        # completed streak until the scheduled settlement task closes it.
        if week.id == through_week.id and not week.is_closed:
            continue
        if not member_week_qualified(member, week):
            break
        streak += 1
    return streak


def serialize_part(part, include_content=True):
    payload = {"id": part.id, "kind": part.kind, "status": part.status, "points": part.points_awarded, "note": part.review_note}
    if include_content:
        payload.update({"text": part.text_content, "link": part.link, "upload": f"/api/attachments/{part.id}" if part.upload else None})
    return payload


def serialize_submission(submission, include_content=True, parts=None):
    selected_parts = parts if parts is not None else submission.parts.all()
    return {"id": submission.id, "member_id": submission.member_id, "member_name": submission.member.display_name, "week": submission.week.number, "submitted_at": submission.submitted_at.isoformat(), "is_valid": submission.is_valid, "visibility": submission.visibility, "parts": [serialize_part(part, include_content) for part in selected_parts]}


@ensure_csrf_cookie
def frontend(request):
    path = BASE_DIR / "index.html"
    if not path.exists():
        raise Http404
    get_token(request)
    raw = repair_text(path.read_text(encoding="utf-8-sig"))
    from django.http import HttpResponse
    response = HttpResponse(raw, content_type="text/html; charset=utf-8")
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    return response


@ensure_csrf_cookie
def auth_page(request):
    path = BASE_DIR / "auth.html"
    if not path.exists():
        raise Http404
    get_token(request)
    from django.http import HttpResponse
    response = HttpResponse(repair_text(path.read_text(encoding="utf-8-sig")), content_type="text/html; charset=utf-8")
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    return response


def repair_text(value):
    import re
    def fix(match):
        chunk = match.group(0)
        try:
            return chunk.encode("latin1").decode("utf-8")
        except UnicodeError:
            return chunk
    return re.sub(r"[^\x00-\x7f]+", fix, value)


def join_team(request):
    if request.method != "POST":
        return api_error("仅支持 POST", 405)
    data = body(request)
    code, name, password, join_password = [str(data.get(key, "")).strip() for key in ("team_code", "name", "password", "join_password")]
    if not code or not join_password or (not request.user.is_authenticated and (not name or not password or len(password) < 8)):
        return api_error("请完整填写信息，密码至少 8 位")
    team = Team.objects.filter(code__iexact=code).first()
    if not team or not check_password(join_password, team.join_password_hash):
        return api_error("团队编号或加入密码错误", 403)
    if TeamMembership.objects.filter(team=team, display_name=name).exists():
        return api_error("该团队中已存在此姓名")
    with transaction.atomic():
        user = request.user if request.user.is_authenticated else User.objects.create(username=create_internal_username(team.code, name), password=make_password(password))
        if TeamMembership.objects.filter(user=user, team=team).exists():
            return api_error("你已经加入该团队")
        admin_invite = str(data.get("admin_invite", "")).strip()
        role = TeamMembership.ADMIN if team.admin_invite_hash and check_password(admin_invite, team.admin_invite_hash) else TeamMembership.MEMBER
        membership = TeamMembership.objects.create(user=user, team=team, display_name=name or user.username, role=role)
    if not request.user.is_authenticated:
        login(request, user)
    request.session["team_id"] = team.id
    return JsonResponse({"ok": True, "team": team.name, "name": membership.display_name})


def register_account(request):
    if request.method != "POST":
        return api_error("仅支持 POST", 405)
    data = body(request)
    account = str(data.get("account", "")).strip()
    password = str(data.get("password", ""))
    confirm_password = str(data.get("confirm_password", ""))
    if not account or len(account) < 3 or len(password) < 8:
        return api_error("账号至少 3 位，密码至少 8 位")
    if password != confirm_password:
        return api_error("两次密码不一致")
    if User.objects.filter(username=account).exists():
        return api_error("该账号已存在")
    user = User.objects.create_user(username=account, password=password)
    login(request, user)
    request.session.pop("team_id", None)
    return JsonResponse({"ok": True, "account": user.username, "teams": []}, status=201)


def login_view(request):
    if request.method != "POST":
        return api_error("仅支持 POST", 405)
    data = body(request)
    code = str(data.get("team_code", "")).strip()
    name = str(data.get("name", "")).strip()
    account = str(data.get("account", name)).strip()
    password = str(data.get("password", "")).strip()
    account_user = User.objects.filter(username=account, is_active=True).first()
    if account_user and check_password(password, account_user.password):
        memberships = TeamMembership.objects.select_related("team").filter(user=account_user, is_active=True)
        if code: memberships = memberships.filter(team__code__iexact=code)
        membership = memberships.first()
        login(request, account_user)
        if membership:
            request.session["team_id"] = membership.team_id
        else:
            request.session.pop("team_id", None)
        return JsonResponse({"ok": True, "team": membership.team.name if membership else None, "name": membership.display_name if membership else account_user.username, "role": membership.role if membership else None, "teams": list(account_user.team_memberships.filter(is_active=True).values("team_id", "team__name", "team__code"))})
    return api_error("账号或密码错误", 403)


def logout_view(request):
    logout(request)
    return JsonResponse({"ok": True})


@api_login_required
@transaction.atomic
def create_team(request):
    if request.method != "POST":
        return api_error("仅支持 POST", 405)
    data = body(request)
    name = str(data.get("team_name", "")).strip()
    code = str(data.get("team_code", "")).strip()
    join_password = str(data.get("join_password", ""))
    if not name or not code or len(join_password) < 8:
        return api_error("请填写团队名称、编号，加入密码至少 8 位")
    if Team.objects.filter(code__iexact=code).exists():
        return api_error("团队编号已存在")
    membership = TeamMembership.objects.filter(user=request.user).first()
    display_name = membership.display_name if membership else str(data.get("display_name", request.user.username)).strip()
    if not display_name:
        return api_error("请填写创建者姓名")
    admin_invite = str(data.get("admin_invite", "")).strip()
    if len(admin_invite) < 6:
        return api_error("请设置至少 6 位管理员邀请码")
    if len(name) > 80 or len(code) > 32 or len(display_name) > 40:
        return api_error('团队名称、编号或成员姓名过长')
    try:
        numeric = {}
        for key, default, upper in [('term_days', 120, 3660), ('min_score', 10, 100000), ('screenshot_points', 1, 10000), ('logic_points', 1, 10000), ('blog_points', 1, 10000)]:
            value = data.get(key, default)
            if isinstance(value, bool) or str(value) != str(int(value)) or not (1 if key == 'term_days' else 0) <= int(value) <= upper:
                raise ValueError()
            numeric[key] = int(value)
    except (ValueError, TypeError):
        return api_error('学期天数或积分设置无效')
    team = Team.objects.create(name=name, code=code, join_password_hash=make_password(join_password), admin_invite_hash=make_password(admin_invite) if admin_invite else "", created_by=request.user)
    duration = numeric['term_days']
    semester = Semester.objects.create(team=team, name=(name + "学期")[:80], starts_on=timezone.localdate(), ends_on=timezone.localdate() + timedelta(days=duration), min_score=numeric["min_score"], screenshot_points=numeric["screenshot_points"], logic_points=numeric["logic_points"], blog_points=numeric["blog_points"])
    build_weeks(semester)
    membership = TeamMembership.objects.create(user=request.user, team=team, display_name=display_name, role=TeamMembership.OWNER)
    request.session["team_id"] = team.id
    return JsonResponse({"ok": True, "team": {"id": team.id, "name": team.name, "code": team.code}, "name": membership.display_name})


@api_login_required
def select_team(request):
    if request.method != "POST": return api_error("仅支持 POST", 405)
    team_id = body(request).get("team_id")
    if not TeamMembership.objects.filter(user=request.user, team_id=team_id, is_active=True).exists(): return api_error("无权进入该团队", 403)
    request.session["team_id"] = team_id
    return JsonResponse({"ok": True})


@api_login_required
def me(request):
    membership = membership_for(request)
    teams = list(request.user.team_memberships.filter(is_active=True).values("team_id", "team__name", "team__code"))
    if not membership:
        return JsonResponse({"name": request.user.username, "team": None, "role": None, "teams": teams, "csrfToken": get_token(request)})
    return JsonResponse({"name": membership.display_name, "team": {"id": membership.team_id, "name": membership.team.name, "code": membership.team.code}, "role": membership.role, "teams": teams, "csrfToken": get_token(request)})


@api_login_required
def dashboard(request):
    membership = membership_for(request)
    if not membership:
        return api_error("未加入当前团队", 403)
    semester = active_semester(membership.team)
    if not semester:
        return JsonResponse({"team": {"id": membership.team_id, "name": membership.team.name}, "semester": None, "current_week": None, "stats": {"rank": None, "memberCount": 0, "streakWeeks": 0, "pendingParts": 0}})
    week = active_week(semester)
    if not week:
        week = semester.weeks.order_by("-number").first()
    parts = SubmissionPart.objects.filter(submission__member=membership, submission__week=week, submission__is_valid=True, status=SubmissionPart.APPROVED)
    score = parts.aggregate(total=Sum("points_awarded"))["total"] or 0
    count = member_week_submissions(membership, week)
    pending_parts = SubmissionPart.objects.filter(submission__member=membership, submission__week=week, status=SubmissionPart.PENDING).count()
    rows = leaderboard_rows_for(membership.team, semester, week)
    current_rank = next((row["rank"] for row in rows if row["memberId"] == membership.id), None)
    previous_week = semester.weeks.filter(number=week.number - 1).first()
    previous_rank = None
    if previous_week:
        previous_rows = leaderboard_rows_for(membership.team, semester, previous_week)
        previous_rank = next((row["rank"] for row in previous_rows if row["memberId"] == membership.id), None)
    now = timezone.now()
    remaining_seconds = max(0, int((week.ends_at - now).total_seconds())) if not week.is_closed else 0
    pulse_weeks = []
    for item in semester.weeks.filter(number__gte=max(1, week.number - 2), number__lte=week.number + 1).order_by("number"):
        pulse_weeks.append({
            "number": item.number,
            "closed": item.is_closed,
            "isCurrent": item.id == week.id,
            "qualified": member_week_qualified(membership, item) if item.is_closed else False,
        })
    return JsonResponse({
        "team": {"id": membership.team_id, "name": membership.team.name},
        "semester": {"id": semester.id, "name": semester.name, "minScore": week.effective_min_score, "minSubmissions": week.effective_min_submissions, "requireBoth": week.effective_require_both, "totalWeeks": semester.weeks.count()},
        "current_week": {"id": week.id, "number": week.number, "startsAt": week.starts_at.isoformat(), "endsAt": week.ends_at.isoformat(), "closed": week.is_closed, "remainingSeconds": remaining_seconds},
        "score": score,
        "submissions": count,
        "visibility": membership.team.visibility_mode,
        "stats": {"rank": current_rank, "previousRank": previous_rank, "memberCount": len(rows), "streakWeeks": member_streak(membership, semester, week), "pendingParts": pending_parts},
        "pulse": pulse_weeks,
    })


@api_login_required
def members(request):
    membership = membership_for(request)
    if not membership:
        return api_error("未加入当前团队", 403)
    semester = active_semester(membership.team)
    week = active_week(semester) if semester else None
    scores, _ = progress_rows(semester) if semester else ({}, {})
    _, counts = progress_rows(semester, week) if week else ({}, {})
    rows = [{'id': member.id, 'name': member.display_name, 'role': member.role,
             'score': scores.get(member.id, 0), 'submissions': counts.get(member.id, 0)}
            for member in membership.team.memberships.filter(is_active=True)]
    return JsonResponse({"members": rows})


@api_login_required
def member_history(request, member_id):
    viewer = membership_for(request)
    if not viewer:
        return api_error("未加入当前团队", 403)
    target = viewer.team.memberships.filter(id=member_id).first()
    if not target:
        return api_error("成员不存在", 404)
    if not viewer.is_admin and target.id != viewer.id and viewer.team.visibility_mode != Team.VISIBILITY_TEAM:
        return api_error("当前团队设置为仅管理员可查看", 403)
    semester_id = request.GET.get('semester')
    if semester_id and not semester_id.isdigit():
        return api_error('学期编号无效')
    semester = (viewer.team.semesters.filter(pk=semester_id).first() if semester_id else
                active_semester(viewer.team) or viewer.team.semesters.order_by('-starts_on').first())
    if semester_id and not semester:
        return api_error('学期不存在', 404)
    if semester and semester.archived_at:
        total = semester.member_totals.filter(member=target).first()
        return JsonResponse({'member': {'id': target.id, 'name': total.display_name if total else target.display_name},
            'archived': True, 'semester': {'id': semester.id, 'name': semester.name},
            'summary': {'score': total.total_score if total else 0, 'submissions': total.total_submissions if total else 0,
                        'qualifiedWeeks': total.qualified_weeks if total else 0, 'qualified': None}, 'submissions': []})
    week_id = request.GET.get("week")
    if week_id and not week_id.isdigit():
        return api_error("周次编号无效")
    queryset = target.submissions.select_related("week").prefetch_related("parts").filter(team=viewer.team, semester=semester)
    if not viewer.is_admin and target.id != viewer.id:
        queryset = queryset.filter(visibility=Submission.VISIBILITY_TEAM)
    if week_id:
        queryset = queryset.filter(week__semester=semester, week__number=week_id)
    visible_submissions = list(queryset)
    summary_week = semester.weeks.filter(number=week_id).first() if week_id and semester else None
    scores, counts = progress_rows(semester, summary_week, [target.id], [item.id for item in visible_submissions])
    summary_score = scores.get(target.id, 0)
    summary_submissions = counts.get(target.id, 0)
    summary_qualified = qualified(summary_score, summary_submissions, summary_week) if summary_week else None
    return JsonResponse({"member": {"id": target.id, "name": target.display_name}, "summary": {"score": summary_score, "submissions": summary_submissions, "qualified": summary_qualified}, "submissions": [serialize_submission(item, True, parts=None if viewer.is_admin or target.id == viewer.id else [part for part in item.parts.all() if part.status == SubmissionPart.APPROVED]) for item in visible_submissions]})


@api_login_required
def submissions(request):
    membership = membership_for(request)
    if not membership:
        return api_error("未加入当前团队", 403)
    if request.method == "GET":
        week_id = request.GET.get("week")
        if week_id and not week_id.isdigit():
            return api_error("周次编号无效")
        queryset = membership.team.submissions.select_related("member", "week").prefetch_related("parts")
        if request.GET.get("mine") == "1":
            queryset = queryset.filter(member=membership)
        if not membership.is_admin:
            queryset = queryset.filter(Q(member=membership) | Q(visibility=Submission.VISIBILITY_TEAM, team__visibility_mode=Team.VISIBILITY_TEAM))
        # The admin queue polls frequently. Keep that response focused on
        # actionable work and bounded so old reviewed history cannot make the
        # dashboard progressively slower as the team grows.
        admin_queue = membership.is_admin and request.GET.get("admin_queue") == "1"
        if admin_queue:
            queryset = queryset.filter(parts__status=SubmissionPart.PENDING).distinct().order_by("-submitted_at")
        if week_id:
            queryset = queryset.filter(week_id=week_id)
        if admin_queue:
            queryset = queryset[:200]
        include_content = membership.is_admin or membership.team.visibility_mode == Team.VISIBILITY_TEAM
        payload = {'submissions': [serialize_submission(item, include_content or item.member_id == membership.id,
            parts=None if membership.is_admin or item.member_id == membership.id else
            [part for part in item.parts.all() if part.status == SubmissionPart.APPROVED]) for item in queryset]}
        if membership.is_admin:
            semester = active_semester(membership.team)
            week = active_week(semester) if semester else None
            stats_week = week or (semester.weeks.order_by("-number").first() if semester else None)
            stats_scope = {"submission__team": membership.team}
            if stats_week:
                stats_scope["submission__week"] = stats_week
            pending = SubmissionPart.objects.filter(status=SubmissionPart.PENDING, **stats_scope).count()
            reviewed = SubmissionPart.objects.filter(status__in=[SubmissionPart.APPROVED, SubmissionPart.REJECTED], **stats_scope).count()
            members = list(membership.team.memberships.filter(is_active=True))
            member_count = len(members)
            current_scores, current_submissions = member_week_progress(members, week)
            qualified = sum(
                1
                for member in members
                if week and week_progress_qualified(current_scores.get(member.id, 0), current_submissions.get(member.id, 0), week)
            )
            previous_week = semester.weeks.filter(ends_at__lte=timezone.now()).order_by("-ends_at").first() if semester else None
            incomplete_members = []
            if previous_week:
                score_by_member, submissions_by_member = member_week_progress(members, previous_week)
                for member in members:
                    score = score_by_member.get(member.id, 0)
                    submissions = submissions_by_member.get(member.id, 0)
                    if not week_progress_qualified(score, submissions, previous_week):
                        incomplete_members.append({
                            "id": member.id,
                            "name": member.display_name,
                            "score": score,
                            "submissions": submissions,
                            "requiredScore": previous_week.effective_min_score,
                            "requiredSubmissions": previous_week.effective_min_submissions,
                            "requiredBoth": previous_week.effective_require_both,
                        })
            payload["stats"] = {
                "pendingParts": pending,
                "reviewedParts": reviewed,
                "qualificationRate": round(qualified / member_count * 100) if member_count else 0,
                "lastWeekNumber": previous_week.number if previous_week else None,
                "lastWeekIncompleteMembers": incomplete_members,
            }
        return JsonResponse(payload)
    if request.method != "POST":
        return api_error("仅支持 GET 或 POST", 405)
    try:
        week_id = int(request.POST.get('week_id', ''))
    except (ValueError, TypeError):
        return api_error('请刷新页面，确认提交周次后重试')
    proof = request.FILES.get('proof')
    if not proof:
        return api_error('通过截图为必填项')
    if proof.size > 5 * 1024 * 1024:
        return api_error('截图不能超过 5MB')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(proof) as picture:
                if picture.format not in {'PNG', 'JPEG', 'WEBP'}:
                    raise ValueError('unsupported image')
                if picture.width * picture.height > 20000000:
                    raise ValueError('image too large')
                extension = {'PNG': '.png', 'JPEG': '.jpg', 'WEBP': '.webp'}[picture.format]
                picture.verify()
            proof.seek(0)
            with Image.open(proof) as picture:
                picture.load()
        proof.seek(0)
        import uuid
        proof.name = uuid.uuid4().hex + extension
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        return api_error('请上传有效的 PNG、JPG 或 WebP 图片')
    logic = request.POST.get('logic', '').strip()
    blog = request.POST.get('blog', '').strip()
    if len(logic) > 50000 or len(blog) > 200:
        return api_error('逻辑最多 50000 字，Blog 链接最多 200 字')
    if blog:
        try:
            URLValidator(schemes=['http', 'https'])(blog)
        except ValidationError:
            return api_error('Blog 必须是有效的 HTTP 或 HTTPS 链接')
    stored_file = None
    try:
        with transaction.atomic():
            target = Week.objects.filter(pk=week_id, semester__team=membership.team).first()
            if not target:
                return api_error('该周次不存在或不属于当前团队', 404)
            semester = Semester.objects.select_for_update().get(pk=target.semester_id)
            week = Week.objects.select_for_update().get(pk=target.pk)
            now = timezone.now()
            if (semester.archived_at or not semester.is_active or week.is_closed
                    or not semester.starts_on <= timezone.localdate(now) <= semester.ends_on
                    or not week.starts_at <= now < week.ends_at):
                return api_error('该周次已截止或尚未开放，不能继续提交，请刷新页面', 409)
            if (week.starts_at, week.ends_at) != week_bounds(semester, week.number):
                return api_error('周次日期异常，请联系管理员修复后再提交', 409)
            submission = Submission.objects.create(team=membership.team, member=membership, semester=semester, week=week, is_valid=True)
            Submission.objects.filter(pk=submission.pk).update(submitted_at=now)
            submission.submitted_at = now
            part = SubmissionPart.objects.create(submission=submission, kind=SubmissionPart.PROOF, upload=proof)
            stored_file = part.upload
            if logic:
                SubmissionPart.objects.create(submission=submission, kind=SubmissionPart.LOGIC, text_content=logic)
            if blog:
                SubmissionPart.objects.create(submission=submission, kind=SubmissionPart.BLOG, link=blog)
    except Exception:
        if stored_file:
            stored_file.delete(save=False)
        raise
    return JsonResponse({'ok': True, 'submission': serialize_submission(submission)}, status=201)


@api_login_required
def showcase(request):
    membership = membership_for(request)
    if not membership:
        return api_error("未加入当前团队", 403)
    if membership.team.visibility_mode != Team.VISIBILITY_TEAM and not membership.is_admin:
        return JsonResponse({"submissions": []})
    queryset = membership.team.submissions.select_related("member", "week").prefetch_related("parts").filter(is_valid=True, parts__status=SubmissionPart.APPROVED).distinct()
    if not membership.is_admin:
        queryset = queryset.filter(visibility=Submission.VISIBILITY_TEAM)
    payload = []
    for item in queryset[:100]:
        approved_parts = list(item.parts.filter(status=SubmissionPart.APPROVED))
        if approved_parts:
            payload.append(serialize_submission(item, True, approved_parts))
    return JsonResponse({"submissions": payload})


@api_login_required
def leaderboard(request):
    membership = membership_for(request)
    if not membership:
        return api_error("未加入当前团队", 403)
    semester = active_semester(membership.team)
    if not semester:
        return JsonResponse({"rows": []})
    scope = request.GET.get("scope", "week")
    week = active_week(semester) or semester.weeks.order_by("-number").first()
    rows = leaderboard_rows_for(membership.team, semester, week if scope == "week" else None)
    for row in rows:
        row["isCurrent"] = row["memberId"] == membership.id
    return JsonResponse({"scope": scope, "rows": rows})


@api_login_required
@transaction.atomic
def bulk_approve(request):
    membership = membership_for(request)
    if not membership or not membership.is_admin:
        return api_error('需要管理员权限', 403)
    if request.method != 'POST':
        return api_error('仅支持 POST', 405)
    data = body(request)
    action = data.get('action', 'approve')
    try:
        if action == 'visibility':
            if data.get('visibility') not in {'team', 'private'}:
                raise ValidationError('展示权限无效')
            if data.get('submission_ids'):
                ids = normalize_ids(data['submission_ids'])
                targets = Submission.objects.filter(team=membership.team, pk__in=ids)
                if set(targets.values_list('pk', flat=True)) != ids:
                    raise ValidationError('提交不存在或不属于当前团队')
            else:
                ids = normalize_ids(data.get('part_ids'))
                parts = SubmissionPart.objects.filter(submission__team=membership.team, pk__in=ids)
                if set(parts.values_list('pk', flat=True)) != ids:
                    raise ValidationError('材料不存在或不属于当前团队')
                targets = Submission.objects.filter(team=membership.team, pk__in=parts.values('submission_id'))
            count = targets.update(visibility=data['visibility'])
            return JsonResponse({'ok': True, 'updated_submissions': count, 'visibility': data['visibility']})
        count = review_submission_parts(request.user, membership.team,
            part_ids=data.get('part_ids'), submission_ids=data.get('submission_ids'),
            action=action, note=data.get('note', '管理员退回' if action == 'reject' else ''))
    except ValidationError as exc:
        return api_error('; '.join(exc.messages))
    return JsonResponse({'ok': True, 'approved_parts': count})


@api_login_required
@transaction.atomic
def team_settings(request):
    membership = membership_for(request)
    if not membership or not membership.is_admin:
        return api_error("需要管理员权限", 403)
    team = membership.team
    if request.method == "GET":
        semester = active_semester(team)
        return JsonResponse({"visibility": team.visibility_mode, "cleanupDelayDays": team.cleanup_delay_days, "hasAdminInvite": bool(team.admin_invite_hash), "semester": {"minSubmissions": semester.min_submissions, "minScore": semester.min_score, "requireBoth": semester.require_both, "screenshotPoints": semester.screenshot_points, "logicPoints": semester.logic_points, "blogPoints": semester.blog_points} if semester else None})
    if request.method != "PUT":
        return api_error("仅支持 GET 或 PUT", 405)
    data = body(request)
    for key in ['cleanupDelayDays', 'minSubmissions', 'minScore', 'screenshotPoints', 'logicPoints', 'blogPoints']:
        if key in data:
            value = data[key]
            if type(value) is not int or not (1 if key == 'cleanupDelayDays' else 0) <= value <= 100000:
                return api_error('设置必须是有效范围内的整数')
    if 'requireBoth' in data and type(data['requireBoth']) is not bool:
        return api_error('达标规则必须为布尔值')
    if data.get("visibility") in {Team.VISIBILITY_TEAM, Team.VISIBILITY_ADMIN}:
        team.visibility_mode = data["visibility"]
    if "cleanupDelayDays" in data:
        team.cleanup_delay_days = max(1, int(data["cleanupDelayDays"]))
    if "adminInvite" in data:
        admin_invite = str(data["adminInvite"]).strip()
        if admin_invite and len(admin_invite) < 6:
            return api_error("管理员邀请码至少 6 位")
        team.admin_invite_hash = make_password(admin_invite) if admin_invite else ""
    team.save(update_fields=["visibility_mode", "cleanup_delay_days", "admin_invite_hash"])
    semester = active_semester(team)
    if semester:
        semester = Semester.objects.select_for_update().get(pk=semester.pk)
        if semester.archived_at:
            return api_error('学期已归档', 409)
        for field, key in (("min_submissions", "minSubmissions"), ("min_score", "minScore"), ("require_both", "requireBoth"), ("screenshot_points", "screenshotPoints"), ("logic_points", "logicPoints"), ("blog_points", "blogPoints")):
            if key in data:
                setattr(semester, field, data[key])
        semester.save()
        refresh_totals(semester)
    return JsonResponse({"ok": True, "visibility": team.visibility_mode})


@api_login_required
def export_xlsx(request):
    membership = membership_for(request)
    if not membership or not membership.is_admin:
        return api_error("需要管理员权限", 403)
    team = membership.team
    semester_id = request.GET.get('semester')
    if semester_id and not semester_id.isdigit():
        return api_error('学期编号无效')
    semester = team.semesters.filter(id=semester_id).first() if semester_id else team.semesters.order_by('-starts_on').first()
    if not semester:
        return api_error("没有可导出的学期", 404)
    workbook = Workbook()
    sheet = workbook.active
    if semester.archived_at:
        sheet.title = '学期汇总'
        sheet.append(['成员姓名', '学期累计积分', '有效提交次数', '达标周数'])
        for total in semester.member_totals.select_related('member').order_by('member_id'):
            sheet.append([total.display_name or total.member.display_name, total.total_score, total.total_submissions, total.qualified_weeks])
            sheet.cell(sheet.max_row, 1).data_type = 's'
        return FileResponse(_workbook_file(workbook), as_attachment=True, filename=f'{team.code}-archive.xlsx')
    sheet.title = "提交与审核"
    headers = ["成员姓名", "周次", "提交时间", "有效提交", "截图审核", "截图积分", "写题逻辑审核", "逻辑积分", "Blog审核", "Blog积分"]
    sheet.append(headers)
    for submission in team.submissions.filter(semester=semester).select_related("member", "week").prefetch_related("parts"):
        by_kind = {part.kind: part for part in submission.parts.all()}
        sheet.append([submission.member.display_name, submission.week.number, submission.submitted_at.astimezone().strftime("%Y-%m-%d %H:%M"), "是" if submission.is_valid else "否", by_kind.get("proof").status if by_kind.get("proof") else "", by_kind.get("proof").points_awarded if by_kind.get("proof") else 0, by_kind.get("logic").status if by_kind.get("logic") else "", by_kind.get("logic").points_awarded if by_kind.get("logic") else 0, by_kind.get("blog").status if by_kind.get("blog") else "", by_kind.get("blog").points_awarded if by_kind.get("blog") else 0])
    for row in sheet.iter_rows(min_row=2):
        row[0].data_type = 's'
    for column, value in enumerate(headers, 1):
        sheet.column_dimensions[get_column_letter(column)].width = max(12, len(value) + 2)
    response = FileResponse(_workbook_file(workbook), as_attachment=True, filename=f"{team.code}-{semester.name}-export.xlsx")
    return response


@api_login_required
def arena(request):
    membership = membership_for(request)
    if not membership:
        return api_error("未加入当前团队", 403)
    if request.method == "GET":
        now = timezone.now()
        item = membership.team.arenas.filter(is_published=True, opens_at__lte=now, closes_at__gt=now).first()
        if not item:
            return JsonResponse({"arena": None})
        return JsonResponse({"arena": {"id": item.id, "title": item.title, "description": item.description, "samples": item.samples, "has_judge_script": bool(item.judge_script), "opens_at": item.opens_at.isoformat(), "closes_at": item.closes_at.isoformat()}})
    if not membership.is_admin:
        return api_error("需要管理员权限", 403)
    data = request.POST if request.content_type and request.content_type.startswith("multipart/") else body(request)
    title = str(data.get("title", "")).strip()
    if not title:
        return api_error("请填写擂台题目标题")
    try:
        opens = datetime.fromisoformat(str(data.get("opens_at")).replace("Z", "+00:00"))
        closes = datetime.fromisoformat(str(data.get("closes_at")).replace("Z", "+00:00"))
        if timezone.is_naive(opens): opens = timezone.make_aware(opens)
        if timezone.is_naive(closes): closes = timezone.make_aware(closes)
    except (TypeError, ValueError):
        return api_error("请填写有效的开放和截止时间")
    if closes <= opens:
        return api_error("截止时间必须晚于开放时间")
    Arena.objects.filter(team=membership.team, is_published=True).update(is_published=False)
    item = Arena.objects.create(team=membership.team, title=title[:120], description=str(data.get("description", "")).strip(), samples=str(data.get("samples", "")).strip(), judge_script=request.FILES.get("judge_script"), opens_at=opens, closes_at=closes, is_published=bool(data.get("is_published", True)), created_by=request.user)
    return JsonResponse({"ok": True, "id": item.id})


@api_login_required
def arena_admin(request):
    membership = membership_for(request)
    if not membership or not membership.is_admin:
        return api_error("需要管理员权限", 403)
    if request.method == "DELETE":
        item = membership.team.arenas.filter(is_published=True).first()
        if item:
            item.is_published = False; item.save(update_fields=["is_published", "updated_at"])
        return JsonResponse({"ok": True})
    item = membership.team.arenas.first()
    return JsonResponse({"arena": {"id": item.id, "title": item.title, "description": item.description, "samples": item.samples, "has_judge_script": bool(item.judge_script), "opens_at": item.opens_at.isoformat(), "closes_at": item.closes_at.isoformat(), "is_published": item.is_published} if item else None})


def _workbook_file(workbook):
    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    return output


@api_login_required
def attachment(request, part_id):
    if request.method not in {'GET', 'HEAD'}:
        return api_error('仅支持 GET 或 HEAD', 405)
    part = SubmissionPart.objects.select_related('submission__team', 'submission__semester').filter(pk=part_id).first()
    if not part or not part.upload or part.submission.semester.archived_at:
        raise Http404
    submission = part.submission
    viewer = membership_for(request, submission.team_id)
    if not viewer or not (viewer.is_admin or viewer.id == submission.member_id or
            (submission.visibility == Submission.VISIBILITY_TEAM and viewer.team.visibility_mode == Team.VISIBILITY_TEAM
             and part.status == SubmissionPart.APPROVED)):
        raise Http404
    if settings.USE_X_ACCEL_REDIRECT:
        response = HttpResponse()
        response['X-Accel-Redirect'] = '/protected-media/' + quote(part.upload.name, safe='/')
    else:
        try:
            response = FileResponse(part.upload.open('rb'))
        except FileNotFoundError:
            raise Http404
    import mimetypes
    content_type = mimetypes.guess_type(part.upload.name)[0]
    if content_type not in {'image/png', 'image/jpeg', 'image/webp'}:
        content_type = 'application/octet-stream'
        response['Content-Disposition'] = 'attachment'
    response['Content-Type'] = content_type
    response['Cache-Control'] = 'private, no-store, max-age=0'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@api_login_required
def semesters(request):
    membership = membership_for(request)
    if not membership:
        return api_error('未加入当前团队', 403)
    return JsonResponse({'semesters': [{'id': item.id, 'name': item.name, 'archived': bool(item.archived_at),
        'weeks': list(item.weeks.values_list('number', flat=True))} for item in membership.team.semesters.all()]})
