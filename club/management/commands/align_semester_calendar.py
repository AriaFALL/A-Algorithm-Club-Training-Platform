from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ValidationError
from club.models import Semester
from club.semester_calendar import align_semester, semester_bounds
from django.utils import timezone


class Command(BaseCommand):
    help = 'Align an active semester with Feb 15 / Aug 1, preserving submissions and week IDs.'

    def add_arguments(self, parser):
        parser.add_argument('--semester', type=int, required=True)
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        semester = Semester.objects.get(pk=options['semester'])
        start, end = semester_bounds(timezone.localdate())
        self.stdout.write(f'{semester.pk}: {semester.starts_on}..{semester.ends_on} -> {start}..{end}')
        if options['apply']:
            try:
                align_semester(semester)
            except ValidationError as exc:
                raise CommandError('; '.join(exc.messages)) from exc
            self.stdout.write(self.style.SUCCESS('Aligned; submission references and reward records preserved.'))
