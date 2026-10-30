from datetime import date
from django.test import TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from .models import Team, TeamMembership, Semester, Submission, SubmissionPart
from .semester_calendar import semester_bounds, align_semester, ensure_current_semester
from .services import build_weeks, validate_week_dates


class SemesterCalendarTests(TestCase):
    def setUp(self):
        user = User.objects.create_user('calendar-member')
        self.team = Team.objects.create(name='Calendar', code='CAL', created_by=user)
        self.member = TeamMembership.objects.create(team=self.team, user=user, display_name='Member')

    def test_boundary_days_and_leap_year(self):
        cases = [
            (date(2026, 2, 14), (date(2025, 8, 1), date(2026, 2, 14))),
            (date(2026, 2, 15), (date(2026, 2, 15), date(2026, 7, 31))),
            (date(2026, 7, 31), (date(2026, 2, 15), date(2026, 7, 31))),
            (date(2026, 8, 1), (date(2026, 8, 1), date(2027, 2, 14))),
            (date(2028, 2, 29), (date(2028, 2, 15), date(2028, 7, 31))),
        ]
        for day, expected in cases:
            with self.subTest(day=day):
                self.assertEqual(semester_bounds(day), expected)

    def test_alignment_preserves_submission_week_and_points(self):
        term = Semester.objects.create(team=self.team, name='Legacy', starts_on=date(2026,10,28), ends_on=date(2027,2,25))
        build_weeks(term)
        week = term.weeks.get(number=1)
        submission = Submission.objects.create(team=self.team, member=self.member, semester=term, week=week, record_date=date(2026,10,29))
        part = SubmissionPart.objects.create(submission=submission, kind='proof', status='approved', points_awarded=3)
        align_semester(term, date(2026,10,30))
        term.refresh_from_db(); week.refresh_from_db(); submission.refresh_from_db(); part.refresh_from_db()
        self.assertEqual((term.starts_on,term.ends_on), (date(2026,8,1),date(2027,2,14)))
        self.assertEqual(submission.week_id, week.pk)
        self.assertEqual(week.number,14)
        self.assertEqual(part.points_awarded,3)
        validate_week_dates(term)
        align_semester(term, date(2026,10,30))
        self.assertEqual(term.weeks.filter(number=14).get().pk, week.pk)

    def test_rollover_is_idempotent_inherits_rules_and_closes_old_term(self):
        term = Semester.objects.create(team=self.team, name='Autumn', starts_on=date(2026,8,1), ends_on=date(2027,2,14), calendar_managed=True, min_score=23, blog_points=5)
        build_weeks(term)
        self.assertEqual(ensure_current_semester(self.team,date(2027,2,14)).pk,term.pk)
        current = ensure_current_semester(self.team,date(2027,2,15))
        self.assertEqual((current.starts_on,current.ends_on),(date(2027,2,15),date(2027,7,31)))
        self.assertEqual((current.min_score,current.blog_points),(23,5))
        term.refresh_from_db()
        self.assertFalse(term.is_active)
        self.assertFalse(term.weeks.filter(is_closed=False).exists())
        self.assertEqual(ensure_current_semester(self.team,date(2027,2,15)).pk,current.pk)
        self.assertEqual(Semester.objects.filter(team=self.team).count(),2)
        self.assertEqual(ensure_current_semester(self.team,date(2027,8,1)).starts_on,date(2027,8,1))

    def test_unsafe_alignment_rolls_back(self):
        term = Semester.objects.create(team=self.team,name='Legacy',starts_on=date(2026,7,1),ends_on=date(2026,12,1))
        build_weeks(term)
        Submission.objects.create(team=self.team, member=self.member, semester=term, week=term.weeks.get(number=1), record_date=date(2026,7,2))
        with self.assertRaises(ValidationError):
            align_semester(term,date(2026,10,30))
        term.refresh_from_db()
        self.assertEqual(term.starts_on,date(2026,7,1))
        self.assertFalse(term.calendar_managed)

    def test_new_team_uses_calendar_instead_of_custom_duration(self):
        import json
        from django.utils import timezone
        root = User.objects.get(username='admin')
        self.client.force_login(root)
        response = self.client.post('/api/auth/create-team', json.dumps({
            'team_name':'New Calendar', 'team_code':'NEWCAL',
            'term_days':120}), content_type='application/json')
        self.assertEqual(response.status_code,200)
        term = Semester.objects.get(team__code='NEWCAL')
        self.assertEqual((term.starts_on,term.ends_on),semester_bounds(timezone.localdate()))
        self.assertTrue(term.calendar_managed)

    def test_last_week_deadline_stops_at_semester_boundary(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from unittest.mock import patch
        term = Semester.objects.create(team=self.team,name='Spring',starts_on=date(2026,2,15),ends_on=date(2026,7,31),calendar_managed=True)
        build_weeks(term)
        self.client.force_login(self.member.user)
        with patch('django.utils.timezone.now',return_value=datetime(2026,7,31,12,tzinfo=ZoneInfo('Asia/Shanghai'))):
            response = self.client.get('/api/dashboard')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['current_week']['endsAt'],'2026-08-01T00:00:00+08:00')
        self.assertEqual(response.json()['current_week']['remainingSeconds'],43200)
