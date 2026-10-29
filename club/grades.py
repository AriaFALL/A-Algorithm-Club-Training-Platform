"""Shanghai academic semesters; promotion dates are February 15 and August 1."""
from datetime import date
from django.utils import timezone

GRADES = ['大一上', '大一下', '大二上', '大二下', '大三+']


def boundaries(start, end):
    return sum(start < date(y, m, d) <= end for y in range(start.year, end.year + 1)
               for m, d in [(2, 15), (8, 1)])


def grade_on(profile, day=None):
    if profile is None or profile.grade is None or profile.grade_date is None:
        return None
    day = day or timezone.localdate()
    if profile.grade == 4:
        return 4
    delta = boundaries(profile.grade_date, day) if day >= profile.grade_date else -boundaries(day, profile.grade_date)
    return min(4, max(0, profile.grade + delta))


def validate_grade(value):
    if isinstance(value, str) and value in ['0','1','2','3','4']:
        return int(value)
    if type(value) is int and value in range(5):
        return value
    raise ValueError('请选择年级：大一上、大一下、大二上、大二下或大三+')
