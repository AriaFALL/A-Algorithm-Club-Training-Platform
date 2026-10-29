"""Authenticated, schema-matched snapshots; archives never live in public media."""
import hashlib
import hmac
import itertools
import json
import logging
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile
from contextlib import contextmanager

from django.apps import apps
from django.conf import settings
from django.core import serializers
from django.core.management import call_command
from django.db import connection, transaction
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone

from .system_guard import database_guard

logger = logging.getLogger(__name__)
FORMAT = 'club-platform-backup-v1'


def root():
    path = Path(settings.SYSTEM_BACKUP_ROOT)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def identifier(value):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise ValueError('备份编号无效')


def write_json(path, value):
    temp = path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    os.replace(temp, path)


def status_path(operation_id):
    return root() / ('operation-' + identifier(operation_id) + '.json')


def read_status(operation_id):
    return json.loads(status_path(operation_id).read_text(encoding='utf-8'))


def status(operation_id, **changes):
    value = read_status(operation_id)
    value.update(changes, updated_at=timezone.now().isoformat())
    write_json(status_path(operation_id), value)


def schema():
    return sorted([list(pair) for pair in MigrationRecorder(connection).applied_migrations()])


def signature(manifest):
    payload = json.dumps(manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    return hmac.new(settings.SECRET_KEY.encode(), b'club-backup-v1\0' + payload, hashlib.sha256).hexdigest()


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def archive_path(backup_id):
    return root() / (identifier(backup_id) + '.zip')


def backup_models():
    # Session restoration would revive obsolete logins. Migration state is schema metadata.
    return [model for model in apps.get_models() if model._meta.managed and model._meta.app_label != 'sessions']


def create_snapshot(label='手动备份'):
    backup_id = str(uuid.uuid4())
    target = archive_path(backup_id)
    temporary = target.with_suffix('.partial')
    with tempfile.TemporaryDirectory(dir=root(), prefix='snapshot-') as temp:
        data_path = Path(temp) / 'database.json'
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            with data_path.open('w', encoding='utf-8') as output:
                serializers.serialize('json', itertools.chain.from_iterable(
                    model._base_manager.order_by('pk').iterator() for model in backup_models()), stream=output)
            migrations = schema()
        files = {'database.json': {'size':data_path.stat().st_size, 'sha256':digest(data_path)}}
        manifest = {'format':FORMAT, 'created_at':timezone.now().isoformat(), 'label':label,
                    'migrations':migrations, 'files':files}
        try:
            with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
                archive.write(data_path, 'database.json')
                media = Path(settings.MEDIA_ROOT)
                if media.exists():
                    for source in sorted(media.rglob('*')):
                        if source.is_symlink():
                            raise ValueError('上传目录包含符号链接，无法安全备份')
                        if not source.is_file():
                            continue
                        name = 'media/' + source.relative_to(media).as_posix()
                        files[name] = {'size':source.stat().st_size, 'sha256':digest(source)}
                        archive.write(source, name)
                manifest['signature'] = signature(manifest)
                archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False))
            os.replace(temporary, target)
            info = {key:manifest[key] for key in ['created_at','label']}
            info.update(id=backup_id, size=target.stat().st_size)
            write_json(target.with_suffix('.json'), info)
            return info
        finally:
            temporary.unlink(missing_ok=True)


@contextmanager
def checked_archive(path):
    """Validate *before* clearing data: signature, schema, paths, size and every hash."""
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(names) != len(set(names)) or 'manifest.json' not in names:
            raise ValueError('备份清单缺失或包含重复文件')
        if archive.getinfo('manifest.json').file_size > 32 * 1024 * 1024:
            raise ValueError('备份清单过大')
        manifest = json.loads(archive.read('manifest.json'))
        signed = manifest.pop('signature', '')
        if not isinstance(signed, str) or not hmac.compare_digest(signed, signature(manifest)):
            raise ValueError('备份校验失败：文件已损坏，或不是使用本系统密钥生成的备份')
        if manifest.get('format') != FORMAT or manifest.get('migrations') != schema():
            raise ValueError('备份版本与当前数据库结构不一致，请使用匹配版本的程序恢复')
        files = manifest.get('files', {})
        if set(names) != set(files) | {'manifest.json'} or 'database.json' not in files:
            raise ValueError('备份文件清单不一致')
        total = 0
        for entry in entries:
            name = entry.filename
            parts = PurePosixPath(name)
            if ('\\' in name or '\x00' in name or parts.is_absolute() or '..' in parts.parts
                    or str(parts) != name or entry.is_dir() or (entry.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError('备份包含不安全的文件路径')
            if name == 'manifest.json':
                continue
            if name != 'database.json' and not name.startswith('media/'):
                raise ValueError('备份包含非预期文件')
            if entry.file_size != files[name].get('size'):
                raise ValueError('备份文件大小校验失败')
            total += entry.file_size
        if total * 2 + 100 * 1024 * 1024 > shutil.disk_usage(root()).free:
            raise ValueError('磁盘剩余空间不足，无法安全恢复')
        with tempfile.TemporaryDirectory(dir=root(), prefix='restore-') as temp:
            folder = Path(temp)
            for name, meta in files.items():
                dest = folder / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                hasher = hashlib.sha256()
                with archive.open(name) as source, dest.open('wb') as output:
                    while chunk := source.read(1024 * 1024):
                        hasher.update(chunk)
                        output.write(chunk)
                if hasher.hexdigest() != meta.get('sha256'):
                    raise ValueError('备份文件内容校验失败')
            yield folder, manifest


def restore_snapshot(backup_id, operation_id):
    source = archive_path(backup_id)
    # All callers must hold the exclusive system lock.
    with checked_archive(source) as (folder, manifest):
        fixture = json.loads((folder / 'database.json').read_text(encoding='utf-8'))
        admins = [row for row in fixture if row.get('model') == 'auth.user' and row.get('fields', {}).get('is_superuser')]
        if len(admins) != 1 or admins[0]['fields'].get('username') != 'admin' or not admins[0]['fields'].get('is_active'):
            raise ValueError('备份必须包含唯一且有效的系统管理员')
        del fixture
        safety = create_snapshot('恢复前自动安全备份')
        status(operation_id, message='校验通过，正在恢复数据与上传文件', safety_backup_id=safety['id'])
        media = Path(settings.MEDIA_ROOT)
        media.mkdir(parents=True, exist_ok=True)
        # MEDIA_ROOT may be a Docker mount point, so never rename the mount itself.
        rollback = media / ('.restore-rollback-' + operation_id)
        rollback.mkdir()
        installed = []
        moved = []
        committed = False
        try:
            with transaction.atomic():
                tables = sorted({m._meta.db_table for m in apps.get_models(include_auto_created=True) if m._meta.managed})
                with connection.cursor() as cursor:
                    cursor.execute('TRUNCATE ' + ', '.join(connection.ops.quote_name(t) for t in tables) + ' RESTART IDENTITY')
                call_command('loaddata', str(folder / 'database.json'), verbosity=0)
                from django.contrib.sessions.models import Session
                Session.objects.all().delete()
                from .models import ContestSyncState, Problem, CleanupJob
                ContestSyncState.objects.filter(status='pending').update(status='failed', remaining=0,
                    messages={'system':'系统已恢复，请重新同步比赛进度'}, finished_at=timezone.now())
                Problem.objects.filter(status__in=['pending','running']).update(status='failed', error='系统已恢复，请重新解析')
                CleanupJob.objects.filter(status='running').update(status='scheduled')
                for item in list(media.iterdir()):
                    if item != rollback:
                        shutil.move(str(item), str(rollback / item.name))
                        moved.append(item.name)
                staged = folder / 'media'
                if staged.exists():
                    for item in staged.iterdir():
                        installed.append(item.name)
                        shutil.copytree(item, media / item.name) if item.is_dir() else shutil.copy2(item, media / item.name)
                # Check all deferred FK constraints before committing the file replacement.
                connection.check_constraints()
                # Rotate before commit so a killed process cannot commit data yet
                # leave old queued tasks eligible. Rotation on rollback is harmless.
                (root() / 'epoch').write_text(str(uuid.uuid4()), encoding='utf-8')
            committed = True
        finally:
            if not committed:
                for name in installed:
                    item = media / name
                    shutil.rmtree(item) if item.is_dir() else item.unlink(missing_ok=True)
                for name in moved:
                    shutil.move(str(rollback / name), str(media / name))
            shutil.rmtree(rollback)
        from django.core.cache import cache
        cache.clear()
        return safety


def run_operation(operation_id):
    operation = read_status(operation_id)
    if operation['state'] != 'queued':
        return
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET lock_timeout = '30s'")
        with database_guard(exclusive=True, wait=True) as acquired:
            if not acquired:
                raise ValueError('系统仍有请求或后台任务运行，请稍后再试')
            # A duplicate process cannot execute the same operation twice.
            if read_status(operation_id)['state'] != 'queued':
                return
            status(operation_id, state='running', message='正在备份，请勿关闭服务')
            if operation['kind'] == 'import':
                source = archive_path(operation['backup_id'])
                try:
                    with checked_archive(source) as (_, manifest):
                        info = {key:manifest[key] for key in ['created_at','label']}
                    info.update(id=operation['backup_id'], size=source.stat().st_size)
                    write_json(source.with_suffix('.json'), info)
                except Exception:
                    source.unlink(missing_ok=True)
                    raise
                status(operation_id, state='completed', message='备份已导入，可在列表中选择恢复')
            elif operation['kind'] == 'backup':
                result = create_snapshot()
                status(operation_id, state='completed', message='备份已完成', backup_id=result['id'])
            else:
                restore_snapshot(operation['backup_id'], operation_id)
                status(operation_id, state='completed', message='恢复已完成，请重新登录', logout=True)
    except Exception as exc:
        logger.exception('System operation %s failed', operation_id)
        message = str(exc) if isinstance(exc, (ValueError, zipfile.BadZipFile)) else '操作失败，已保留安全备份；请查看服务日志后重试'
        status(operation_id, state='failed', message=message[:500])


def start_operation(kind, backup_id=None):
    operation_id = str(uuid.uuid4())
    value = {'id':operation_id, 'kind':kind, 'backup_id':backup_id, 'state':'queued',
             'created_at':timezone.now().isoformat(), 'message':'等待执行'}
    write_json(status_path(operation_id), value)
    try:
        with (root() / ('operation-' + operation_id + '.log')).open('ab') as output:
            process = subprocess.Popen([sys.executable, str(Path(settings.BASE_DIR) / 'manage.py'),
                              'system_backup_operation', operation_id], cwd=settings.BASE_DIR,
                             stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                             start_new_session=True)
        status(operation_id, pid=process.pid)
    except OSError:
        status(operation_id, state='failed', message='无法启动操作进程，请检查服务状态')
        raise ValueError('无法启动操作，请稍后重试')
    return value
