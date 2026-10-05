import io
import json
import tempfile
from datetime import timedelta
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from PIL import Image
from django.contrib.auth.models import User
from django.contrib.staticfiles import finders
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings
from django.test import TransactionTestCase
from django.db import connections
from django.utils import timezone
from openpyxl import load_workbook

from .models import CleanupJob, Semester, SemesterMemberTotal, Submission, SubmissionPart, Team, TeamMembership
from .services import approve_submission_parts, build_weeks, cleanup_semester, settle_week, week_bounds
from . import tests as original_tests


class RegressionTests(TestCase):
    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        self.settings_override = override_settings(MEDIA_ROOT=self.media.name, USE_X_ACCEL_REDIRECT=False)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        original_tests.ClubApiTests.setUp(self)
        self.week = self.semester.weeks.get(starts_at__lte=timezone.now(), ends_at__gt=timezone.now())

    def image(self):
        output = io.BytesIO()
        Image.new('RGB', (3, 3), 'white').save(output, format='PNG')
        return SimpleUploadedFile('proof.png', output.getvalue(), content_type='image/png')

    def submission(self, valid=True, week=None):
        submission = Submission.objects.create(team=self.team, member=self.member, semester=self.semester,
                                               week=week or self.week, is_valid=valid)
        part = SubmissionPart.objects.create(submission=submission, kind='proof', upload=self.image())
        return submission, part

    def review(self, ids, action='approve'):
        return self.client.post('/api/admin/submissions/bulk-approve',
            json.dumps({'submission_ids': ids, 'action': action}), content_type='application/json')

    def test_weeks_are_contiguous_and_repeatable(self):
        weeks = build_weeks(self.semester)
        self.assertEqual([w.id for w in weeks], [w.id for w in build_weeks(self.semester)])
        for left, right in zip(weeks, weeks[1:]):
            self.assertEqual(left.ends_at, right.starts_at)

    def test_missing_empty_and_malformed_review_targets_change_nothing(self):
        submission, part = self.submission()
        for ids in [[], [99999999], [submission.id, 99999999], ['bad'], 'bad', [True]]:
            self.assertEqual(self.review(ids).status_code, 400)
            part.refresh_from_db()
            self.assertEqual(part.status, 'pending')
        with self.assertRaises(ValidationError):
            approve_submission_parts(self.user, self.team)

    def test_cross_team_review_is_rejected_without_partial_approval(self):
        submission, part = self.submission()
        team = Team.objects.create(name='other', code='OTHER', created_by=self.user)
        member = TeamMembership.objects.create(team=team, user=self.user, display_name='other', role='owner')
        semester = Semester.objects.create(team=team, name='other', starts_on=self.semester.starts_on, ends_on=self.semester.ends_on)
        week = build_weeks(semester)[0]
        other = Submission.objects.create(team=team, member=member, semester=semester, week=week)
        other_part = SubmissionPart.objects.create(submission=other, kind='logic', text_content='other')
        self.assertEqual(self.review([submission.id, other.id]).status_code, 400)
        part.refresh_from_db(); other_part.refresh_from_db()
        self.assertEqual((part.status, other_part.status), ('pending', 'pending'))

    def test_deadline_rejects_old_week_and_never_moves_submission(self):
        end = self.week.ends_at
        with patch('django.utils.timezone.now', return_value=end):
            response = self.client.post('/api/submissions', {'week_id': self.week.id, 'proof': self.image()})
        self.assertEqual(response.status_code, 409)
        self.assertFalse(Submission.objects.exists())

    def test_before_deadline_accepts_and_requires_explicit_week(self):
        self.assertEqual(self.client.post('/api/submissions', {'proof': self.image()}).status_code, 400)
        with patch('django.utils.timezone.now', return_value=self.week.ends_at - timedelta(microseconds=1)):
            response = self.client.post('/api/submissions', {'week_id': self.week.id, 'proof': self.image()})
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Submission.objects.get().week_id, self.week.id)

    def test_fake_image_and_unsafe_blog_are_rejected(self):
        fake = SimpleUploadedFile('fake.png', b'not an image', content_type='image/png')
        self.assertEqual(self.client.post('/api/submissions', {'week_id': self.week.id, 'proof': fake}).status_code, 400)
        self.assertEqual(self.client.post('/api/submissions', {'week_id': self.week.id, 'proof': self.image(), 'blog': 'javascript:alert(1)'}).status_code, 400)
        self.assertFalse(Submission.objects.exists())

    def test_late_review_updates_settled_totals_and_is_idempotent(self):
        self.semester.min_submissions = 1
        self.semester.min_score = 1
        self.semester.save()
        submission, part = self.submission()
        with patch('django.utils.timezone.now', return_value=self.week.ends_at):
            settle_week(self.week)
            self.assertEqual(self.review([submission.id]).status_code, 200)
        total = SemesterMemberTotal.objects.get(member=self.member, semester=self.semester)
        self.assertEqual((total.total_score, total.total_submissions, total.qualified_weeks), (1, 1, 1))
        self.assertEqual(self.review([submission.id]).json()['approved_parts'], 0)
        self.assertEqual(part.review_logs.count(), 1)

    def test_private_attachment_checks_every_request(self):
        submission, part = self.submission()
        approve_submission_parts(self.user, self.team, submission_ids=[submission.id])
        member_user = User.objects.create_user('reader', password='password-123')
        TeamMembership.objects.create(team=self.team, user=member_user, display_name='reader')
        reader = Client(); reader.force_login(member_user)
        url = f'/api/attachments/{part.id}'
        self.assertEqual(Client().get(url).status_code, 401)
        response = reader.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response['Cache-Control']); list(response.streaming_content)
        submission.visibility = 'private'; submission.save()
        self.assertEqual(reader.get(url).status_code, 404)
        response = self.client.get(url); self.assertEqual(response.status_code, 200); list(response.streaming_content)
        with override_settings(DEBUG=True):
            self.assertEqual(self.client.get(part.upload.url).status_code, 404)

    def test_unrelated_account_and_unapproved_material_are_hidden(self):
        submission, part = self.submission()
        other = User.objects.create_user('outsider')
        reader = Client(); reader.force_login(other)
        self.assertEqual(reader.get(f'/api/attachments/{part.id}').status_code, 404)
        TeamMembership.objects.create(team=self.team, user=other, display_name='outsider')
        self.assertEqual(reader.get(f'/api/attachments/{part.id}').status_code, 404)

    @override_settings(USE_X_ACCEL_REDIRECT=True)
    def test_nginx_handoff_is_private(self):
        _, part = self.submission()
        response = self.client.get(f'/api/attachments/{part.id}')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response['X-Accel-Redirect'].startswith('/protected-media/submissions/'))

    def test_static_finders_do_not_expose_source(self):
        for name in ['config/settings.py', 'club/views.py', 'requirements.txt', 'README.md']:
            self.assertIsNone(finders.find(name))

    def test_cleanup_retry_preserves_totals_and_exports_archive(self):
        good, part = self.submission()
        invalid, _ = self.submission(valid=False)
        pending, _ = self.submission()
        approve_submission_parts(self.user, self.team, submission_ids=[good.id, invalid.id])
        with patch('club.services.default_storage.delete', side_effect=OSError('temporary failure')):
            with self.assertRaises(OSError):
                cleanup_semester(self.semester)
        total = SemesterMemberTotal.objects.get(semester=self.semester, member=self.member)
        self.assertEqual((total.total_score, total.total_submissions), (1, 1))
        self.assertFalse(self.semester.submissions.exists())
        job = CleanupJob.objects.get(semester=self.semester)
        self.assertEqual(job.status, 'failed'); self.assertTrue(job.pending_files)
        cleanup_semester(self.semester)
        cleanup_semester(self.semester)
        total.refresh_from_db(); job.refresh_from_db()
        self.assertEqual((total.total_score, total.total_submissions), (1, 1))
        self.assertEqual(job.status, 'completed'); self.assertEqual(job.pending_files, [])
        self.assertFalse(part.upload.storage.exists(part.upload.name))
        history = self.client.get(f'/api/members/{self.member.id}/history?semester={self.semester.id}&week=1').json()
        self.assertTrue(history['archived']); self.assertEqual(history['summary']['score'], 1)
        response = self.client.get(f'/api/export?semester={self.semester.id}')
        workbook = load_workbook(io.BytesIO(b''.join(response.streaming_content)))
        self.assertEqual(list(workbook.active.values)[1][1:3], (1, 1))

    def test_archived_semester_cannot_be_reviewed(self):
        submission, _ = self.submission()
        Semester.objects.filter(pk=self.semester.pk).update(archived_at=timezone.now())
        self.assertEqual(self.review([submission.id]).status_code, 400)

    def test_repair_is_explicit_and_reassigns_by_submission_time(self):
        first, second = list(self.semester.weeks.order_by('number'))[:2]
        submission, _ = self.submission(week=first)
        Submission.objects.filter(pk=submission.pk).update(submitted_at=second.starts_at + timedelta(hours=1))
        second.starts_at = first.starts_at + timedelta(days=1)
        second.ends_at = second.starts_at + timedelta(days=7)
        second.save()
        call_command('repair_weeks', semester=self.semester.id, stdout=io.StringIO())
        submission.refresh_from_db(); self.assertEqual(submission.week_id, first.id)
        call_command('repair_weeks', semester=self.semester.id, apply=True, stdout=io.StringIO())
        second.refresh_from_db(); submission.refresh_from_db()
        self.assertEqual((second.starts_at, second.ends_at), week_bounds(self.semester, 2))
        self.assertEqual(submission.week_id, second.id)

    def test_bad_team_settings_do_not_partially_create_team(self):
        response = self.client.post('/api/auth/create-team', json.dumps({'team_name': 'bad', 'team_code': 'BAD',
            'join_password': 'password-123', 'admin_invite': 'password-123', 'term_days': 'invalid'}), content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Team.objects.filter(code='BAD').exists())

    def test_bad_legacy_dates_cannot_be_settled_or_archived(self):
        self.week.starts_at += timedelta(days=1)
        self.week.save(update_fields=['starts_at'])
        with self.assertRaises(ValidationError):
            settle_week(self.week)
        with self.assertRaises(ValidationError):
            cleanup_semester(self.semester)
        self.semester.refresh_from_db()
        self.assertIsNone(self.semester.archived_at)

    def test_repair_preserves_intentionally_closed_correct_week(self):
        self.week.is_closed = True
        self.week.save(update_fields=['is_closed'])
        call_command('repair_weeks', semester=self.semester.id, apply=True, stdout=io.StringIO())
        self.week.refresh_from_db()
        self.assertTrue(self.week.is_closed)

    def test_repair_rolls_back_when_valid_submission_is_outside_term(self):
        submission, _ = self.submission()
        Submission.objects.filter(pk=submission.pk).update(submitted_at=self.week.starts_at - timedelta(days=100))
        self.week.starts_at += timedelta(days=1)
        self.week.save(update_fields=['starts_at'])
        previous_start = self.week.starts_at
        with self.assertRaises(CommandError):
            call_command('repair_weeks', semester=self.semester.id, apply=True, stdout=io.StringIO())
        self.week.refresh_from_db()
        self.assertEqual(self.week.starts_at, previous_start)


class ConcurrentReviewTests(TransactionTestCase):
    def setUp(self):
        if connections['default'].vendor != 'postgresql':
            self.skipTest('Concurrency checks require PostgreSQL row locks')
        original_tests.ClubApiTests.setUp(self)
        self.submission = Submission.objects.create(team=self.team, member=self.member, semester=self.semester,
                                                    week=self.semester.weeks.first())
        self.part = SubmissionPart.objects.create(submission=self.submission, kind='logic', text_content='proof of reasoning')

    def run_concurrently(self, functions):
        barrier = Barrier(len(functions))
        def run(function):
            try:
                barrier.wait(timeout=10)
                return function()
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=len(functions)) as executor:
            return list(executor.map(run, functions))

    def approve(self):
        return approve_submission_parts(self.user, self.team, submission_ids=[self.submission.id])

    def test_concurrent_approvals_award_points_once(self):
        results = self.run_concurrently([self.approve, self.approve])
        self.assertEqual(sorted(results), [0, 1])
        self.assertEqual(self.part.review_logs.count(), 1)
        self.assertEqual(SemesterMemberTotal.objects.get(semester=self.semester, member=self.member).total_score, 1)

    def test_review_and_archive_have_a_consistent_snapshot(self):
        def review():
            try:
                return self.approve()
            except ValidationError:
                return 0  # Archive won the lock; review must not change the snapshot.
        results = self.run_concurrently([review, lambda: cleanup_semester(self.semester)])
        total = SemesterMemberTotal.objects.get(semester=self.semester, member=self.member)
        self.assertEqual(total.total_score, results[0])
        self.assertFalse(self.semester.submissions.exists())
