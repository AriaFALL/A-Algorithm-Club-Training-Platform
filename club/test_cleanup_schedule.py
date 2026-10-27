import importlib
import json
from datetime import timedelta
from unittest.mock import patch
from django.apps import apps
from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase, Client
from django.utils import timezone
from . import test_community as fixtures
from .models import Semester, Submission, CleanupJob, SemesterMemberTotal
from .tasks import run_cleanup


class CleanupScheduleTests(TestCase):
    setUp = fixtures.CommunityTests.setUp
    image = fixtures.CommunityTests.image
    submit = fixtures.CommunityTests.submit

    def root(self):
        self.client.force_login(User.objects.get(username='admin'))
        return f'/api/management/teams/{self.team.id}/cleanup'

    def schedule(self, endpoint, selected):
        return self.client.post(endpoint, json.dumps({'cleanup_time':selected.isoformat()}), content_type='application/json')

    def test_seven_day_grace_and_cleanup_retains_totals(self):
        submission = self.submit()
        selected = timezone.now() + timedelta(hours=1)
        endpoint = self.root()
        result = self.schedule(endpoint,selected)
        self.assertEqual(result.status_code,200,result.content)
        self.semester.refresh_from_db()
        self.assertEqual(self.semester.cleanup_at,selected+timedelta(days=7))
        job = CleanupJob.objects.get(semester=self.semester)
        with patch('club.tasks.timezone.now', return_value=selected+timedelta(days=6,hours=23)):
            self.assertEqual(run_cleanup(job.id)['status'],'cancelled')
            self.assertTrue(Submission.objects.filter(pk=submission.id).exists())
        with patch('club.tasks.timezone.now', return_value=selected+timedelta(days=7)):
            self.assertEqual(run_cleanup(job.id)['status'],'completed')
        self.assertFalse(Submission.objects.filter(pk=submission.id).exists())
        self.assertEqual(SemesterMemberTotal.objects.get(member=self.author_member).total_score,3)
        self.assertTrue(User.objects.filter(pk=self.author.id).exists())
        self.assertEqual(self.client.delete(endpoint).status_code,409)

    def test_cancel_reset_and_stale_queued_task(self):
        submission = self.submit()
        endpoint = self.root()
        selected = timezone.now()+timedelta(hours=1)
        self.assertEqual(self.schedule(endpoint,selected).status_code,200)
        job_id = CleanupJob.objects.get(semester=self.semester).id
        self.assertEqual(self.schedule(endpoint,selected).status_code,409)
        self.assertEqual(self.client.delete(endpoint).status_code,200)
        self.semester.refresh_from_db()
        self.assertIsNone(self.semester.cleanup_at)
        self.assertEqual(run_cleanup(job_id)['status'],'cancelled')
        self.assertEqual(self.schedule(endpoint,selected+timedelta(days=1)).status_code,200)
        self.assertEqual(run_cleanup(job_id)['status'],'cancelled')
        self.assertTrue(Submission.objects.filter(pk=submission.id).exists())
        data = self.client.get(f'/api/management/teams/{self.team.id}/settings').json()
        self.assertIn('cleanup',data)
        self.assertGreaterEqual(data['cleanup']['days_left'],8)

    def test_permission_invalid_date_and_no_automatic_schedule(self):
        self.assertIsNone(self.semester.cleanup_at)
        endpoint=f'/api/management/teams/{self.team.id}/cleanup'
        self.assertEqual(self.client.delete(endpoint).status_code,403)
        self.root()
        for value in ['invalid', (timezone.now()-timedelta(days=1)).isoformat(), None]:
            self.assertEqual(self.client.post(endpoint,json.dumps({'cleanup_time':value}),content_type='application/json').status_code,400)

    def test_upgrade_cancels_only_legacy_schedule_and_preserves_records(self):
        item=self.submit()
        self.semester.cleanup_at=timezone.now()+timedelta(days=20)
        self.semester.save()
        CleanupJob.objects.create(semester=self.semester,scheduled_for=self.semester.cleanup_at)
        module=importlib.import_module('club.migrations.0014_manual_cleanup_schedule')
        with connection.schema_editor() as editor:
            module.cancel_legacy_schedules(apps,editor)
        self.semester.refresh_from_db()
        self.assertIsNone(self.semester.cleanup_at)
        self.assertFalse(CleanupJob.objects.filter(semester=self.semester).exists())
        self.assertTrue(Submission.objects.filter(pk=item.id).exists())
