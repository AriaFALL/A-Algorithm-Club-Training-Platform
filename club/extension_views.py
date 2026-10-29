import io
import uuid
from pathlib import Path

from PIL import Image, ImageOps
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import JsonResponse, FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods
from .models import ExtensionResource, FileDeletion
from .views import api_login_required, api_error, membership_for


def allowed(request):
    return request.user.is_superuser or bool(membership_for(request))


def data(item):
    return dict(id=item.pk, title=item.title, description=item.description, url=item.url,
                kind='file' if item.upload else 'link', filename=item.filename,
                href=f'/api/extensions/{item.pk}/download' if item.upload else item.url,
                cover=f'/api/extensions/{item.pk}/cover' if item.cover else None)


@api_login_required
@require_http_methods(['GET', 'POST', 'DELETE'])
def resources(request, resource_id=None):
    if not allowed(request):
        return api_error('请先加入团队', 403)
    if request.method == 'GET':
        return JsonResponse({'items': [data(i) for i in ExtensionResource.objects.all()],
                             'can_manage': request.user.is_superuser})
    if not request.user.is_superuser:
        return api_error('仅系统管理员可管理资源', 403)
    if request.method == 'DELETE':
        with transaction.atomic():
            item = get_object_or_404(ExtensionResource.objects.select_for_update(), pk=resource_id)
            for field in (item.upload, item.cover):
                if field: FileDeletion.objects.create(name=field.name)
            item.delete()
        return JsonResponse({'ok': True})
    title = request.POST.get('title', '').strip()
    description = request.POST.get('description', '').strip()
    kind = request.POST.get('kind')
    url = request.POST.get('url', '').strip()
    upload = request.FILES.get('file')
    cover = request.FILES.get('cover')
    if not title or len(title) > 100 or len(description) > 300 or kind not in ('link', 'file'):
        return api_error('请填写标题（最多100字）、简介（最多300字）和资源类型')
    if kind == 'link':
        try:
            URLValidator(schemes=['http', 'https'])(url)
            if len(url) > 2000: raise ValidationError('URL too long')
        except ValidationError:
            return api_error('请输入有效的 HTTP 或 HTTPS 链接')
    if cover:
        try:
            picture = Image.open(cover)
            if picture.format not in {'PNG', 'JPEG', 'WEBP'} or picture.width * picture.height > 16000000:
                raise ValueError()
            picture = ImageOps.fit(ImageOps.exif_transpose(picture).convert('RGB'), (800, 800))
            output = io.BytesIO(); picture.save(output, 'JPEG', quality=88)
            cover = ContentFile(output.getvalue(), name=f'{uuid.uuid4().hex}.jpg')
        except (OSError, ValueError, Image.DecompressionBombError):
            return api_error('请上传有效的 PNG、JPEG 或 WebP 封面（最多1600万像素）')
    stored = []
    try:
        with transaction.atomic():
            item = get_object_or_404(ExtensionResource.objects.select_for_update(), pk=resource_id) if resource_id else ExtensionResource()
            if kind == 'file' and not upload and not item.upload:
                return api_error('请选择要下载的文件')
            item.title, item.description = title, description
            item.url = url if kind == 'link' else ''
            if kind == 'link' or upload:
                if item.upload: FileDeletion.objects.create(name=item.upload.name)
                item.upload = ''
                item.filename = ''
            if kind == 'file' and upload:
                item.filename = Path(upload.name).name[:255]
                item.upload.save(uuid.uuid4().hex, upload, save=False)
                stored.append(item.upload.name)
            if cover or request.POST.get('remove_cover') == '1':
                if item.cover: FileDeletion.objects.create(name=item.cover.name)
                item.cover = ''
                if cover:
                    item.cover.save(cover.name, cover, save=False)
                    stored.append(item.cover.name)
            item.save()
    except Exception:
        for name in stored: FileDeletion.objects.create(name=name)
        raise
    return JsonResponse({'item': data(item)})


@api_login_required
@require_http_methods(['GET'])
def asset(request, resource_id, cover=False):
    if not allowed(request): return api_error('请先加入团队', 403)
    item = get_object_or_404(ExtensionResource, pk=resource_id)
    field = item.cover if cover else item.upload
    if not field: raise Http404
    try:
        response = FileResponse(field.open('rb'), as_attachment=not cover,
                                filename='cover.jpg' if cover else item.filename,
                                content_type='image/jpeg' if cover else 'application/octet-stream')
    except FileNotFoundError:
        raise Http404
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
