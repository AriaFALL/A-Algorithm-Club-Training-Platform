from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from club.models import Semester, Week
from club.services import build_weeks, refresh_totals, week_bounds


class Command(BaseCommand):
    help = 'Audit week dates and submission assignments; --apply repairs a selected semester atomically.'

    def add_arguments(self, parser):
        parser.add_argument('--semester', type=int)
        parser.add_argument('--apply', action='store_true')

    @transaction.atomic
    def handle(self, *args, **options):
        if options['apply'] and not options['semester']:
            raise CommandError('--apply requires --semester ID; audit each semester first.')
        semesters = Semester.objects.filter(archived_at__isnull=True).order_by('pk')
        if options['semester']:
            semesters = semesters.filter(pk=options['semester'])
        if options['apply']:
            semesters = semesters.select_for_update()
        for semester in semesters:
            weeks = list(semester.weeks.order_by('number'))
            monday = semester.starts_on - timedelta(days=semester.starts_on.weekday())
            assignments = []
            unsafe = []
            for submission in semester.submissions.select_related('week').order_by('pk'):
                day = timezone.localdate(submission.submitted_at)
                if not semester.starts_on <= day <= semester.ends_on:
                    if submission.is_valid:
                        unsafe.append(submission.pk)
                    continue
                number = (day - monday).days // 7 + 1
                if submission.week.number != number:
                    assignments.append((submission, number))
            changed = [week for week in weeks if (week.starts_at, week.ends_at) != week_bounds(semester, week.number)]
            self.stdout.write(f'Semester {semester.pk}: dates={len(changed)}, reassignments={len(assignments)}, outside_semester={unsafe}')
            for week in changed:
                start, end = week_bounds(semester, week.number)
                self.stdout.write(f'  Week {week.number}: {week.starts_at.isoformat()} -> {start.isoformat()}, end -> {end.isoformat()}')
            for submission, number in assignments:
                self.stdout.write(f'  Submission {submission.pk}: week {submission.week.number} -> {number}')
            if options['apply']:
                if unsafe:
                    raise CommandError('Valid submissions outside semester dates need manual review; nothing was changed.')
                build_weeks(semester)
                now = timezone.now()
                for week in semester.weeks.all():
                    start, end = week_bounds(semester, week.number)
                    # Trailing legacy weeks outside the term remain closed and retain their records.
                    unchanged_dates = (week.starts_at, week.ends_at) == (start, end)
                    closed = end <= now or timezone.localdate(start) > semester.ends_on or (unchanged_dates and week.is_closed)
                    Week.objects.filter(pk=week.pk).update(starts_at=start, ends_at=end, is_closed=closed, settled_at=now if closed else None)
                for submission, number in assignments:
                    submission.week = semester.weeks.get(number=number)
                    submission.save(update_fields=['week'])
                refresh_totals(semester)
                self.stdout.write(self.style.SUCCESS('Repaired dates, assignments, closure state and totals.'))
