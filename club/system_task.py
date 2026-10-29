from celery import Task
from celery.exceptions import Ignore
from celery.signals import before_task_publish
from .system_guard import database_guard, epoch


@before_task_publish.connect
def stamp_system_epoch(headers=None, **kwargs):
    if headers is not None:
        headers['system_epoch'] = epoch()


class SystemGuardedTask(Task):
    def __call__(self, *args, **kwargs):
        generation = epoch()
        with database_guard(wait=True):
            # Discard queued/in-flight requests originating before a restore.
            expected = (self.request.headers or {}).get('system_epoch', generation if self.request.called_directly else 'initial')
            if generation != epoch() or expected != epoch():
                raise Ignore()
            return super().__call__(*args, **kwargs)
