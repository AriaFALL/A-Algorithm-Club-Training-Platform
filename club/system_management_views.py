import json
import uuid
import os
from pathlib import Path
from django.contrib.auth import logout
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import FileResponse, JsonResponse, Http404
from django.views.decorators.http import require_http_methods
from .management_views import administrator_required
from .views import api_error, body
from . import system_backups as backups


@administrator_required
@require_http_methods(['POST'])
def change_admin_password(request):
    data = body(request)
    old, new, confirm = [data.get(key) for key in ['old_password','new_password','confirm_password']]
    if not all(isinstance(value, str) for value in (old,new,confirm)) or not 8 <= len(new) <= 128:
        return api_error('新密码需为8–128个字符')
    if new != confirm:
        return api_error('两次新密码不一致')
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=request.user.pk)
        if not user.check_password(old):
            return api_error('当前密码不正确')
        if new == old:
            return api_error('新密码不能与当前密码相同')
        try:
            validate_password(new, user)
        except ValidationError as exc:
            return api_error('；'.join(exc.messages))
        user.set_password(new)
        user.save(update_fields=['password'])
    # Re-read committed data before reporting success or destroying the session.
    saved = User.objects.get(pk=user.pk)
    if not saved.check_password(new):
        return api_error('密码保存确认失败，请重新登录后核对', 500)
    logout(request)
    return JsonResponse({'ok':True, 'logout':True, 'message':'密码已保存，请使用新密码重新登录'})


@administrator_required
@require_http_methods(['GET','POST'])
def backup_collection(request):
    if request.method == 'GET':
        values = []
        for path in backups.root().glob('*.json'):
            if path.name.startswith('operation-'):
                continue
            try:
                info = json.loads(path.read_text(encoding='utf-8'))
                if backups.archive_path(info['id']).is_file():
                    values.append(info)
            except (ValueError, KeyError, OSError):
                continue
        return JsonResponse({'backups':sorted(values, key=lambda item:item['created_at'], reverse=True)})
    try:
        return JsonResponse(backups.start_operation('backup'), status=202)
    except ValueError as exc:
        return api_error(str(exc))


@administrator_required
@require_http_methods(['POST'])
def import_backup(request):
    upload = request.FILES.get('file')
    if upload is None or not upload.name.lower().endswith('.zip'):
        return api_error('请选择本系统导出的ZIP备份文件')
    backup_id = str(uuid.uuid4())
    path = backups.archive_path(backup_id)
    try:
        with path.open('wb') as output:
            for chunk in upload.chunks():
                output.write(chunk)
        return JsonResponse(backups.start_operation('import', backup_id), status=202)
    except (ValueError, OSError):
        path.unlink(missing_ok=True)
        return api_error('备份上传失败，请检查磁盘空间后重试')


@administrator_required
@require_http_methods(['GET','DELETE'])
def backup_detail(request, backup_id):
    path = backups.archive_path(backup_id)
    if not path.is_file() or not path.with_suffix('.json').is_file():
        raise Http404
    if request.method == 'DELETE':
        path.unlink()
        path.with_suffix('.json').unlink(missing_ok=True)
        return JsonResponse({'ok':True})
    response = FileResponse(path.open('rb'), as_attachment=True, filename=f'club-backup-{backup_id}.zip', content_type='application/zip')
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@administrator_required
@require_http_methods(['POST'])
def restore_backup(request, backup_id):
    data = body(request)
    if data.get('confirmation') != '恢复全部数据':
        return api_error('请输入“恢复全部数据”确认')
    password = data.get('password')
    if not isinstance(password, str) or not request.user.check_password(password):
        return api_error('当前管理员密码不正确')
    if not backups.archive_path(backup_id).is_file() or not backups.archive_path(backup_id).with_suffix('.json').is_file():
        raise Http404
    try:
        return JsonResponse(backups.start_operation('restore', str(backup_id)), status=202)
    except ValueError as exc:
        return api_error(str(exc))


@require_http_methods(['GET'])
def operation_status(request, operation_id):
    # UUID4 is a bearer token returned only by the administrator's start request.
    # This endpoint must remain usable after restore invalidates all sessions.
    try:
        operation = backups.read_status(operation_id)
    except (FileNotFoundError, ValueError):
        raise Http404
    if operation['state'] in ['queued','running'] and operation.get('pid'):
        try:
            os.kill(operation['pid'], 0)
            command = Path('/proc') / str(operation['pid']) / 'cmdline'
            if command.exists() and str(operation_id).encode() not in command.read_bytes():
                raise ProcessLookupError
        except ProcessLookupError:
            backups.status(operation_id, state='failed', message='操作进程已中断，请检查服务和恢复前安全备份后重试')
            operation = backups.read_status(operation_id)
    response = JsonResponse({key:operation[key] for key in ['id','kind','state','message','backup_id','logout','safety_backup_id'] if key in operation})
    response['Cache-Control'] = 'private, no-store'
    response['Referrer-Policy'] = 'no-referrer'
    return response
