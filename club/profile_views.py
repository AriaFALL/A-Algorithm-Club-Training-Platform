"""Own-account profile editing and explicitly requested platform synchronization."""
import io
import uuid
from datetime import timedelta

from PIL import Image, ImageOps, UnidentifiedImageError
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.http import FileResponse, Http404, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import FileDeletion, PlatformBinding, UserProfile, TeamMembership
from .views import api_login_required, api_error, body, membership_for
from .platform_sync import PLATFORMS, validate_account


def avatar_url(user):
    profile = UserProfile.objects.filter(user=user).first()
    return '/api/profile/avatar' if profile and profile.avatar else None


def serialize_binding(binding):
    pending = binding.status == 'pending'
    expired = pending and binding.requested_at < timezone.now() - timedelta(minutes=4)
    return {
        'platform': binding.platform, 'account': binding.account,
        'snapshot': binding.snapshot,
        'status': 'failed' if expired else binding.status,
        'error': '同步超时，请重新同步' if expired else binding.error,
        'synced_at': binding.synced_at.isoformat() if binding.synced_at else None,
    }


def profile_data(request):
    member = membership_for(request)
    from .grades import grade_on, GRADES
    personal = UserProfile.objects.filter(user=request.user).first()
    grade = grade_on(personal)
    return {'name': member.display_name, 'account': request.user.username,
            'grade': grade, 'grade_label': GRADES[grade] if grade is not None else '注册资料缺失，请联系管理员',
            'grade_options': GRADES,
            'team_name': member.team.name, 'avatar': avatar_url(request.user),
            'platforms': PLATFORMS,
            'bindings': [serialize_binding(b) for b in request.user.platform_bindings.all()]}


def eligible(request):
    member = membership_for(request)
    return member if member and member.pk and not request.user.is_superuser else None


@api_login_required
@require_http_methods(['GET', 'POST'])
def profile(request):
    member = eligible(request)
    if not member:
        return api_error('个人信息页仅供团队管理员与普通成员使用', 403)
    if request.method == 'GET':
        return JsonResponse(profile_data(request))
    if 'grade' in request.POST:
        return api_error('年级仅可在注册时选择',400)
    name = request.POST.get('name', member.display_name).strip()
    if not name or len(name) > 40:
        return api_error('昵称需为 1–40 个字符', 400)
    upload = request.FILES.get('avatar')
    avatar = None
    if upload:
        if upload.size > 3 * 1024 * 1024:
            return api_error('头像不能超过 3 MB', 400)
        try:
            image = Image.open(upload)
            if image.format not in {'PNG', 'JPEG', 'WEBP'} or image.width * image.height > 16000000:
                raise ValueError()
            image = ImageOps.exif_transpose(image).convert('RGB')
            image = ImageOps.fit(image, (256, 256))
            output = io.BytesIO(); image.save(output, format='JPEG', quality=88)
            avatar = ContentFile(output.getvalue(), name=f'{uuid.uuid4().hex}.jpg')
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
            return api_error('请上传有效的 PNG、JPEG 或 WebP 图片（最多 1600 万像素）', 400)
    stored = None
    try:
        with transaction.atomic():
            member = TeamMembership.objects.select_for_update().get(pk=member.pk)
            member.display_name = name
            member.save(update_fields=['display_name'])
            personal, _ = UserProfile.objects.get_or_create(user=request.user)
            if avatar:
                old = personal.avatar.name
                personal.avatar = avatar
                personal.save(update_fields=['avatar'])
                stored = personal.avatar.name
                if old:
                    FileDeletion.objects.create(name=old)
    except IntegrityError:
        if stored:
            FileDeletion.objects.create(name=stored)
        return api_error('当前团队中已有此昵称，请换一个昵称', 409)
    return JsonResponse(profile_data(request))


@api_login_required
@require_http_methods(['POST'])
def change_password(request):
    if request.user.is_superuser:
        from .system_management_views import change_admin_password
        return change_admin_password(request)
    from django.contrib.auth import update_session_auth_hash
    from django.contrib.auth.models import User
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError
    data = body(request)
    old, new, confirm = (data.get(k) for k in ('old_password','new_password','confirm_password'))
    if not all(isinstance(v,str) for v in (old,new,confirm)) or len(new)<8 or len(new)>128:
        return api_error('新密码需为 8–128 个字符',400)
    if new != confirm:
        return api_error('两次新密码不一致',400)
    with transaction.atomic():
        user=User.objects.select_for_update().get(pk=request.user.pk)
        if not user.check_password(old):
            return api_error('当前密码不正确',400)
        if old == new:
            return api_error('新密码不能与当前密码相同',400)
        try:
            validate_password(new,user)
        except ValidationError as exc:
            return api_error('；'.join(exc.messages),400)
        user.set_password(new);user.save(update_fields=['password'])
    update_session_auth_hash(request,user)
    return JsonResponse({'ok':True})


@api_login_required
@require_http_methods(['GET', 'HEAD'])
def avatar(request, member_id=None):
    user = request.user
    if member_id is not None:
        viewer = membership_for(request)
        if not viewer:
            raise Http404
        member = TeamMembership.objects.filter(pk=member_id, team=viewer.team,
            is_active=True, user__is_active=True).first()
        if not member:
            raise Http404
        user = member.user
    personal = UserProfile.objects.filter(user=user).first()
    if not personal or not personal.avatar:
        raise Http404
    try:
        response = FileResponse(personal.avatar.open('rb'), content_type='image/jpeg')
    except FileNotFoundError:
        raise Http404
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def enqueue(binding):
    from .tasks import sync_platform_binding
    try:
        sync_platform_binding.delay(binding.pk, str(binding.sync_token))
    except Exception:
        PlatformBinding.objects.filter(pk=binding.pk, sync_token=binding.sync_token).update(
            status='failed', error='同步服务暂不可用，请稍后重试')


@api_login_required
@require_http_methods(['PUT', 'POST', 'DELETE'])
def platform_binding(request, platform):
    if not eligible(request):
        return api_error('请先加入团队', 403)
    if platform not in PLATFORMS:
        return api_error('不支持的平台', 400)
    data = body(request)
    if 'cookie' in data:
        return api_error('洛谷查询 Cookie 由系统管理员统一配置',400)
    with transaction.atomic():
        # Serialize changes per user, including first-time binding creation.
        from django.contrib.auth.models import User
        User.objects.select_for_update().get(pk=request.user.pk)
        binding = PlatformBinding.objects.filter(user=request.user, platform=platform).first()
        if request.method == 'DELETE':
            if binding:
                binding.delete()
            return JsonResponse({'ok': True})
        if request.method == 'POST' and not binding:
            return api_error('请先绑定账号', 400)
        if binding and binding.requested_at > timezone.now() - timedelta(seconds=60):
            return api_error('请等待一分钟后再同步', 429)
        if request.method == 'PUT':
            try:
                account = validate_account(platform, data.get('account'))
            except ValueError as exc:
                return api_error(str(exc), 400)
            changed = not binding or binding.account != account
            if not binding:
                binding = PlatformBinding(user=request.user, platform=platform)
            if changed:
                binding.snapshot = {}; binding.synced_at = None
            binding.account = account
        binding.sync_token = uuid.uuid4()
        binding.requested_at = timezone.now()
        binding.status = 'pending'; binding.error = ''
        binding.save()
        transaction.on_commit(lambda: enqueue(binding))
    binding.refresh_from_db()
    return JsonResponse(serialize_binding(binding), status=202)
