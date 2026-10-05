import json
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
from .services import approve_submission_parts, build_weeks

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
        return json.loads(request.body or "{}")
    except json.JSONDecodeError:
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
    semester = team.semesters.filter(is_active=True, starts_on__lte=today, ends_on__gte=today).first()
    if semester:
        build_weeks(semester)
    return semester


def active_week(semester):
    now = timezone.now()
    return semester.weeks.filter(starts_at__lte=now, ends_at__gt=now, is_closed=False).first()


def member_week_score(member, week):
    return SubmissionPart.objects.filter(
        submission__member=member,
        submission__week=week,
        submission__is_valid=True,
        status=SubmissionPart.APPROVED,
    ).aggregate(total=Sum("points_awarded"))["total"] or 0


def member_week_submissions(member, week):
    return Submission.objects.filter(
        member=member,
        week=week,
        is_valid=True,
        parts__kind=SubmissionPart.PROOF,
        parts__status=SubmissionPart.APPROVED,
    ).distinct().count()


def week_progress_qualified(score, submissions, week):
    if week.effective_require_both:
        return submissions >= week.effective_min_submissions and score >= week.effective_min_score
    return submissions >= week.effective_min_submissions or score >= week.effective_min_score


def member_week_qualified(member, week):
    return week_progress_qualified(member_week_score(member, week), member_week_submissions(member, week), week)


def member_week_progress(members, week):
    """Return approved score and proof counts with two aggregate queries."""
    if not members or not week:
        return {}, {}
    member_ids = [member.id for member in members]
    scores = {
        row["submission__member_id"]: row["score"] or 0
        for row in SubmissionPart.objects.filter(
            submission__week=week,
            submission__is_valid=True,
            submission__member_id__in=member_ids,
            status=SubmissionPart.APPROVED,
        ).values("submission__member_id").annotate(score=Sum("points_awarded"))
    }
    submissions = {
        row["member_id"]: row["submissions"]
        for row in Submission.objects.filter(
            week=week,
            is_valid=True,
            member_id__in=member_ids,
            parts__kind=SubmissionPart.PROOF,
            parts__status=SubmissionPart.APPROVED,
        ).values("member_id").annotate(submissions=Count("id", distinct=True))
    }
    return scores, submissions


def leaderboard_rows_for(team, semester, week=None):
    rows = []
    for member in team.memberships.filter(is_active=True):
        parts = SubmissionPart.objects.filter(
            submission__member=member,
            submission__semester=semester,
            submission__is_valid=True,
            status=SubmissionPart.APPROVED,
        )
        if week:
            parts = parts.filter(submission__week=week)
        score = parts.aggregate(total=Sum("points_awarded"))["total"] or 0
        submissions = Submission.objects.filter(
            member=member,
            semester=semester,
            is_valid=True,
            **({"week": week} if week else {}),
        ).filter(parts__kind=SubmissionPart.PROOF, parts__status=SubmissionPart.APPROVED).distinct().count()
        rows.append({"memberId": member.id, "name": member.display_name, "score": score, "submissions": submissions})
    rows.sort(key=lambda row: (-row["score"], -row["submissions"], row["name"]))
    for index, row in enumerate(rows, 1):
        row["rank"] = index
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
        payload.update({"text": part.text_content, "link": part.link, "upload": part.upload.url if part.upload else None})
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
    team = Team.objects.create(name=name, code=code, join_password_hash=make_password(join_password), admin_invite_hash=make_password(admin_invite) if admin_invite else "", created_by=request.user)
    duration = max(1, int(data.get("term_days", 120)))
    semester = Semester.objects.create(team=team, name=name + "学期", starts_on=timezone.localdate(), ends_on=timezone.localdate() + timedelta(days=duration), min_score=int(data.get("min_score", 10)), screenshot_points=int(data.get("screenshot_points", 1)), logic_points=int(data.get("logic_points", 1)), blog_points=int(data.get("blog_points", 1)))
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
    rows = []
    for member in membership.team.memberships.filter(is_active=True):
        score = SubmissionPart.objects.filter(submission__member=member, submission__semester=semester, submission__is_valid=True, status=SubmissionPart.APPROVED).aggregate(total=Sum("points_awarded"))["total"] or 0 if semester else 0
        count = Submission.objects.filter(member=member, week=week, is_valid=True, parts__kind=SubmissionPart.PROOF, parts__status=SubmissionPart.APPROVED).distinct().count() if week else 0
        rows.append({"id": member.id, "name": member.display_name, "role": member.role, "score": score, "submissions": count})
    return JsonResponse({"members": rows})


@api_login_required
def member_history(request, member_id):
    viewer = membership_for(request)
    if not viewer:
        return api_error("未加入当前团队", 403)
    target = viewer.team.memberships.filter(id=member_id, is_active=True).first()
    if not target:
        return api_error("成员不存在", 404)
    if not viewer.is_admin and target.id != viewer.id and viewer.team.visibility_mode != Team.VISIBILITY_TEAM:
        return api_error("当前团队设置为仅管理员可查看", 403)
    semester = active_semester(viewer.team) or viewer.team.semesters.order_by("-starts_on").first()
    week_id = request.GET.get("week")
    queryset = target.submissions.select_related("week").prefetch_related("parts").filter(team=viewer.team, semester=semester)
    if not viewer.is_admin and target.id != viewer.id:
        queryset = queryset.filter(visibility=Submission.VISIBILITY_TEAM)
    if week_id:
        queryset = queryset.filter(week__semester=semester, week__number=week_id)
    visible_submissions = list(queryset)
    summary_week = semester.weeks.filter(number=week_id).first() if week_id and semester else None
    if summary_week:
        week_submissions = [item for item in visible_submissions if item.week_id == summary_week.id and item.is_valid]
        summary_score = sum(part.points_awarded for item in week_submissions for part in item.parts.all() if part.status == SubmissionPart.APPROVED)
        summary_submissions = sum(1 for item in week_submissions if any(part.kind == SubmissionPart.PROOF and part.status == SubmissionPart.APPROVED for part in item.parts.all()))
        summary_qualified = (summary_submissions >= summary_week.effective_min_submissions and summary_score >= summary_week.effective_min_score) if summary_week.effective_require_both else (summary_submissions >= summary_week.effective_min_submissions or summary_score >= summary_week.effective_min_score)
    else:
        summary_score = sum(part.points_awarded for item in visible_submissions for part in item.parts.all() if item.is_valid and part.status == SubmissionPart.APPROVED) if semester else 0
        summary_submissions = sum(1 for item in visible_submissions if item.is_valid)
        summary_qualified = None
    return JsonResponse({"member": {"id": target.id, "name": target.display_name}, "summary": {"score": summary_score, "submissions": summary_submissions, "qualified": summary_qualified}, "submissions": [serialize_submission(item, viewer.is_admin or target.id == viewer.id or viewer.team.visibility_mode == Team.VISIBILITY_TEAM) for item in visible_submissions]})


@api_login_required
def submissions(request):
    membership = membership_for(request)
    if not membership:
        return api_error("未加入当前团队", 403)
    if request.method == "GET":
        week_id = request.GET.get("week")
        queryset = membership.team.submissions.select_related("member", "week").prefetch_related("parts")
        if request.GET.get("mine") == "1":
            queryset = queryset.filter(member=membership)
        if not membership.is_admin:
            queryset = queryset.filter(Q(member=membership) | Q(visibility=Submission.VISIBILITY_TEAM, team__visibility_mode=Team.VISIBILITY_TEAM))
        if week_id:
            queryset = queryset.filter(week_id=week_id)
        include_content = membership.is_admin or membership.team.visibility_mode == Team.VISIBILITY_TEAM
        payload = {"submissions": [serialize_submission(item, include_content or item.member_id == membership.id) for item in queryset]}
        if membership.is_admin:
            semester = active_semester(membership.team)
            week = active_week(semester) if semester else None
            pending = SubmissionPart.objects.filter(submission__team=membership.team, status=SubmissionPart.PENDING).count()
            reviewed = SubmissionPart.objects.filter(submission__team=membership.team, status__in=[SubmissionPart.APPROVED, SubmissionPart.REJECTED]).count()
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
    semester = active_semester(membership.team)
    week = active_week(semester) if semester else None
    if not semester or not week:
        return api_error("当前没有开放的周次", 409)
    proof = request.FILES.get("proof")
    if not proof:
        return api_error("通过截图为必填项")
    if proof.content_type not in {"image/png", "image/jpeg", "image/webp"} or proof.size > 5 * 1024 * 1024:
        return api_error("截图必须是 PNG/JPG/WebP，且不超过 5MB")
    with transaction.atomic():
        submission = Submission.objects.create(team=membership.team, member=membership, semester=semester, week=week, is_valid=not week.is_closed)
        SubmissionPart.objects.create(submission=submission, kind=SubmissionPart.PROOF, upload=proof)
        logic = request.POST.get("logic", "").strip()
        if logic:
            SubmissionPart.objects.create(submission=submission, kind=SubmissionPart.LOGIC, text_content=logic)
        blog = request.POST.get("blog", "").strip()
        if blog:
            SubmissionPart.objects.create(submission=submission, kind=SubmissionPart.BLOG, link=blog)
    return JsonResponse({"ok": True, "submission": serialize_submission(submission)}, status=201)


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
        return api_error("需要管理员权限", 403)
    if request.method != "POST":
        return api_error("仅支持 POST", 405)
    data = body(request)
    submission_ids = data.get("submission_ids", [])
    part_ids = data.get("part_ids", [])
    parts = SubmissionPart.objects.filter(submission__team=membership.team)
    if submission_ids:
        parts = parts.filter(submission_id__in=submission_ids)
    elif part_ids:
        parts = parts.filter(id__in=part_ids)
    else:
        return api_error("请选择要审批的提交")
    part_ids_to_review = list(parts.values_list("id", flat=True))
    if data.get("action") == "visibility":
        visibility = data.get("visibility")
        if visibility not in {Submission.VISIBILITY_TEAM, Submission.VISIBILITY_PRIVATE}:
            return api_error("展示权限无效")
        if submission_ids:
            target_submission_ids = submission_ids
        else:
            target_submission_ids = parts.values("submission_id")
        changed = Submission.objects.filter(
            team=membership.team,
            id__in=target_submission_ids,
        ).update(visibility=visibility)
        return JsonResponse({"ok": True, "updated_submissions": changed, "visibility": visibility})
    if data.get("action") == "reject":
        changed = 0
        for part in SubmissionPart.objects.select_for_update().filter(id__in=part_ids_to_review, status=SubmissionPart.PENDING):
            part.status = SubmissionPart.REJECTED
            part.points_awarded = 0
            part.review_note = str(data.get("note", "管理员退回"))[:500]
            part.reviewed_at = timezone.now()
            part.reviewed_by = request.user
            part.save(update_fields=["status", "points_awarded", "review_note", "reviewed_at", "reviewed_by"])
            ReviewLog.objects.create(submission=part.submission, part=part, actor=request.user, action="reject", detail={"note": part.review_note})
            changed += 1
        count = changed
    else:
        count = approve_submission_parts(request.user, part_ids_to_review, note=str(data.get("note", ""))[:500])
    return JsonResponse({"ok": True, "approved_parts": count})


@api_login_required
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
        for field, key in (("min_submissions", "minSubmissions"), ("min_score", "minScore"), ("require_both", "requireBoth"), ("screenshot_points", "screenshotPoints"), ("logic_points", "logicPoints"), ("blog_points", "blogPoints")):
            if key in data:
                setattr(semester, field, data[key])
        semester.save()
    return JsonResponse({"ok": True, "visibility": team.visibility_mode})


@api_login_required
def export_xlsx(request):
    membership = membership_for(request)
    if not membership or not membership.is_admin:
        return api_error("需要管理员权限", 403)
    team = membership.team
    semester = team.semesters.filter(id=request.GET.get("semester"), is_active=False).first() if request.GET.get("semester") else team.semesters.order_by("-starts_on").first()
    if not semester:
        return api_error("没有可导出的学期", 404)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "提交与审核"
    headers = ["成员姓名", "周次", "提交时间", "有效提交", "截图审核", "截图积分", "写题逻辑审核", "逻辑积分", "Blog审核", "Blog积分"]
    sheet.append(headers)
    for submission in team.submissions.filter(semester=semester).select_related("member", "week").prefetch_related("parts"):
        by_kind = {part.kind: part for part in submission.parts.all()}
        sheet.append([submission.member.display_name, submission.week.number, submission.submitted_at.astimezone().strftime("%Y-%m-%d %H:%M"), "是" if submission.is_valid else "否", by_kind.get("proof").status if by_kind.get("proof") else "", by_kind.get("proof").points_awarded if by_kind.get("proof") else 0, by_kind.get("logic").status if by_kind.get("logic") else "", by_kind.get("logic").points_awarded if by_kind.get("logic") else 0, by_kind.get("blog").status if by_kind.get("blog") else "", by_kind.get("blog").points_awarded if by_kind.get("blog") else 0])
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
    import tempfile
    file = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    workbook.save(file.name)
    file.seek(0)
    return open(file.name, "rb")

