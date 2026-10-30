"""Academic terms switch at local midnight on February 15 and August 1."""
from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Semester, Team, Week
from .services import build_weeks, refresh_totals, validate_week_dates


def semester_bounds(day):
    if day >= date(day.year, 8, 1):
        return date(day.year, 8, 1), date(day.year + 1, 2, 14)
    if day >= date(day.year, 2, 15):
        return date(day.year, 2, 15), date(day.year, 7, 31)
    return date(day.year - 1, 8, 1), date(day.year, 2, 14)


def semester_name(start):
    return f'{start.year}年春季学期' if start.month == 2 else f'{start.year}—{start.year + 1}年秋季学期'


@transaction.atomic
def ensure_current_semester(team, day=None):
    day = day or timezone.localdate()
    # Follow the existing semester-before-team lock order used by scoring/configuration.
    terms = list(Semester.objects.select_for_update().filter(team=team, calendar_managed=True).order_by('-starts_on'))
    if not terms or terms[0].archived_at or not terms[0].is_active:
        return None
    Team.objects.select_for_update().get(pk=team.pk)
    start, end = semester_bounds(day)
    for term in terms:
        if term.starts_on == start and term.ends_on == end:
            return term if term.is_active and not term.archived_at else None
    template = terms[0]
    if template.starts_on > start or template.ends_on >= day:
        return None
    rules = {field: getattr(template, field) for field in
             ('min_submissions', 'min_score', 'require_both', 'screenshot_points', 'logic_points', 'blog_points')}
    for term in terms:
        if term.is_active and term.ends_on < start and not term.archived_at:
            validate_week_dates(term)
            term.weeks.filter(is_closed=False).update(is_closed=True, settled_at=timezone.now())
            refresh_totals(term)
    Semester.objects.filter(pk__in=[term.pk for term in terms], is_active=True).update(is_active=False)
    current = Semester.objects.create(team=team, name=semester_name(start), starts_on=start,
                                      ends_on=end, calendar_managed=True, **rules)
    build_weeks(current)
    return current


@transaction.atomic
def align_semester(semester, day=None):
    """Preserve week IDs/dates and submission references while renumbering an existing term."""
    semester = Semester.objects.select_for_update().get(pk=semester.pk)
    Team.objects.select_for_update().get(pk=semester.team_id)
    if semester.archived_at or not semester.is_active:
        raise ValidationError('只能调整未归档的活动学期')
    validate_week_dates(semester)
    start, end = semester_bounds(day or timezone.localdate())
    if semester.submissions.filter(record_date__lt=start).exists() or semester.submissions.filter(record_date__gt=end).exists():
        raise ValidationError('存在新学期范围外的提交，未作调整，请先检查这些记录')
    if Semester.objects.filter(team=semester.team, starts_on__lte=end, ends_on__gte=start).exclude(pk=semester.pk).exists():
        raise ValidationError('调整后的日期与其他学期重叠，未作调整')
    monday = start - timedelta(days=start.weekday())
    weeks = list(semester.weeks.select_for_update().order_by('number'))
    mapped = []
    for week in weeks:
        week_day = timezone.localdate(week.starts_at)
        if week_day > end or timezone.localdate(week.ends_at) <= start:
            if week.submissions.exists():
                raise ValidationError('范围外周次仍有关联提交，未作调整')
            week.delete()
        else:
            mapped.append((week, (week_day - monday).days // 7 + 1))
    # Vacate the unique semester/number keys before assigning the new numbers.
    offset = max((w.number for w in weeks), default=0) + 1000
    for week, number in mapped:
        Week.objects.filter(pk=week.pk).update(number=number + offset)
    for week, number in mapped:
        Week.objects.filter(pk=week.pk).update(number=number)
    semester.starts_on, semester.ends_on = start, end
    semester.calendar_managed = True
    semester.name = semester_name(start)
    semester.save(update_fields=['starts_on', 'ends_on', 'calendar_managed', 'name'])
    build_weeks(semester)
    refresh_totals(semester)
    return semester
