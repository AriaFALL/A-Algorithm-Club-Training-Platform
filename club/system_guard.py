"""Coordinate API requests and background work with snapshot/restore operations."""
from contextlib import contextmanager
from pathlib import Path
from django.conf import settings
from django.db import connection
from django.http import JsonResponse

LOCK_KEY = 739184206


def epoch():
    try:
        return (Path(settings.SYSTEM_BACKUP_ROOT) / 'epoch').read_text().strip()
    except FileNotFoundError:
        return 'initial'


@contextmanager
def database_guard(exclusive=False, wait=False):
    # PostgreSQL session locks also cover files, which transaction locks alone cannot.
    mode = '' if exclusive else '_shared'
    function = 'pg_advisory_lock' if wait else 'pg_try_advisory_lock'
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT {function}{mode}(%s)', [LOCK_KEY])
        acquired = True if wait else cursor.fetchone()[0]
    try:
        yield acquired
    finally:
        if acquired:
            with connection.cursor() as cursor:
                cursor.execute(f'SELECT pg_advisory_unlock{mode}(%s)', [LOCK_KEY])


class SystemOperationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Status is an unguessable operation token and never reads the database.
        if request.path.startswith('/api/management/system-operations/'):
            return self.get_response(request)
        if not request.path.startswith(('/api/', '/admin/')):
            return self.get_response(request)
        with database_guard() as acquired:
            if not acquired:
                response = JsonResponse({'error':'系统正在备份或恢复，请稍后重试'}, status=503)
                response['Retry-After'] = '5'
                return response
            return self.get_response(request)
