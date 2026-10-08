from datetime import timedelta

from django.db import connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from .models import Submission, SubmissionPart, TeamMembership
from .services import build_weeks, refresh_totals
from . import tests as original_tests


class QueryEfficiencyTests(TestCase):
    def setUp(self):
        original_tests.ClubApiTests.setUp(self)

    def test_existing_long_semester_needs_one_read(self):
        self.semester.ends_on += timedelta(days=365)
        self.semester.save()
        weeks = build_weeks(self.semester)
        with self.assertNumQueries(1):
            repeated = build_weeks(self.semester)
        self.assertEqual([w.pk for w in repeated], [w.pk for w in weeks])

    def test_missing_weeks_do_not_rewrite_existing_history(self):
        weeks = build_weeks(self.semester)
        first = weeks[0]
        first.starts_at += timedelta(hours=1)
        first.is_closed = True
        first.min_score = 99
        first.save()
        missing_number = weeks[-1].number
        weeks[-1].delete()
        rebuilt = build_weeks(self.semester)
        first.refresh_from_db()
        self.assertEqual(first.starts_at, rebuilt[0].starts_at)
        self.assertTrue(first.is_closed)
        self.assertEqual(first.min_score, 99)
        self.assertEqual([w.number for w in rebuilt], list(range(1, missing_number + 1)))

    def test_forty_member_totals_update_in_bounded_queries(self):
        TeamMembership.objects.bulk_create([
            TeamMembership(team=self.team, user=self.user, display_name=f'Member {i}', is_active=i != 0)
            for i in range(39)
        ])
        week = self.semester.weeks.first()
        week.is_closed = True
        week.min_score = 2
        week.min_submissions = 1
        week.require_both = True
        week.save()
        good = Submission.objects.create(team=self.team, member=self.member, semester=self.semester, week=week)
        proof = SubmissionPart.objects.create(submission=good, kind='proof', status='approved', points_awarded=2)
        SubmissionPart.objects.create(submission=good, kind='logic', status='pending', points_awarded=100)
        invalid = Submission.objects.create(team=self.team, member=self.member, semester=self.semester, week=week, is_valid=False)
        SubmissionPart.objects.create(submission=invalid, kind='proof', status='approved', points_awarded=100)
        with transaction.atomic(), CaptureQueriesContext(connection) as queries:
            refresh_totals(self.semester)
        self.assertLessEqual(len(queries), 12)
        self.assertEqual(self.semester.member_totals.count(), 40)
        total = self.semester.member_totals.get(member=self.member)
        self.assertEqual((total.total_score, total.total_submissions, total.qualified_weeks), (2, 1, 1))
        previous_time = total.finalized_at
        proof.points_awarded = 1
        proof.save()
        self.member.display_name = 'Renamed'
        self.member.save()
        with transaction.atomic(), CaptureQueriesContext(connection) as queries:
            refresh_totals(self.semester)
        self.assertLessEqual(len(queries), 12)
        total.refresh_from_db()
        self.assertEqual((total.total_score, total.total_submissions, total.qualified_weeks), (1, 1, 0))
        self.assertEqual(total.display_name, 'Renamed')
        self.assertGreaterEqual(total.finalized_at, previous_time)
        self.assertEqual(self.semester.member_totals.count(), 40)
        self.semester.archived_at = timezone.now()
        with self.assertNumQueries(0):
            refresh_totals(self.semester)

    def test_semester_list_query_count_does_not_grow(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get('/api/semesters')
        self.assertEqual(response.status_code, 200)
        initial_queries = len(queries)
        expected = response.json()['semesters'][0]['weeks']
        self.semester.pk = None
        self.semester.name = 'Another semester'
        self.semester.save()
        build_weeks(self.semester)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get('/api/semesters')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(queries), initial_queries)
        self.assertEqual(len(response.json()['semesters']), 2)
        self.assertTrue(all(item['weeks'] == expected for item in response.json()['semesters']))
