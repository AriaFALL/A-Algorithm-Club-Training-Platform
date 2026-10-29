from django.core.management.base import BaseCommand
from club.system_backups import run_operation
from club.system_backups import read_status
import time


class Command(BaseCommand):
    help = 'Run a privileged system snapshot operation outside the HTTP request timeout.'

    def add_arguments(self, parser):
        parser.add_argument('operation_id')

    def handle(self, operation_id, **options):
        # Parent persists the PID before the child begins mutating status.
        deadline = time.monotonic() + 5
        while 'pid' not in read_status(operation_id) and time.monotonic() < deadline:
            time.sleep(0.05)
        run_operation(operation_id)
