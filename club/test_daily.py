from datetime import datetime, timedelta
from unittest.mock import patch
from django.utils import timezone
from django.test import TestCase
from . import test_community as fixtures
URL = fixtures.URL


class DailyRecordsTests(TestCase):
    setUp = fixtures.CommunityTests.setUp
    image = fixtures.CommunityTests.image
    def test_daily_backfill_streak_and_rejection(self):
        start = timezone.localdate(self.week.starts_at)
        today = min(start + timedelta(days=3), self.semester.ends_on)
        now = timezone.make_aware(datetime.combine(today, datetime.min.time())) + timedelta(hours=12)
        with patch('club.views.timezone.now', return_value=now):
            for offset in [0, 2]:
                response = self.client.post('/api/submissions', {'week_id': self.week.pk, 'problem_url': URL,
                    'record_date': (today-timedelta(days=offset)).isoformat(), 'proof': self.image()})
                self.assertEqual(response.status_code, 201, response.content)
            data = self.client.get('/api/dashboard').json()
            self.assertEqual(len(data['pulse']), 21)
            for day in data['pulse']:
                if day['date'] < start.isoformat() or day['date'] > today.isoformat():
                    self.assertFalse(day['canSubmit'])
            self.assertEqual(data['streakDays'], 1)
            response = self.client.post('/api/submissions', {'week_id': self.week.pk, 'problem_url': URL,
                'record_date': (today-timedelta(days=1)).isoformat(), 'proof': self.image()})
            self.assertEqual(response.status_code, 201, response.content)
            self.assertEqual(self.client.get('/api/dashboard').json()['streakDays'], 3)
            submission = self.author_member.submissions.get(pk=response.json()['submission']['id'])
            self.assertEqual(submission.record_date, today-timedelta(days=1))
            submission.is_valid = False
            submission.save()
            self.assertEqual(self.client.get('/api/dashboard').json()['streakDays'], 1)
            for invalid in [today+timedelta(days=1), start-timedelta(days=1)]:
                response = self.client.post('/api/submissions', {'week_id': self.week.pk, 'problem_url': URL,
                    'record_date': invalid.isoformat(), 'proof': self.image()})
                self.assertEqual(response.status_code, 409)
            response = self.client.post(f'/api/submissions/{submission.pk}/resubmit', {'week_id': self.week.pk,
                'problem_url': URL, 'record_date': today.isoformat(), 'proof': self.image()})
            self.assertEqual(response.status_code, 201, response.content)
            submission.refresh_from_db()
            self.assertEqual(submission.record_date, today-timedelta(days=1))
            self.assertEqual(self.client.get('/api/dashboard').json()['streakDays'], 3)
