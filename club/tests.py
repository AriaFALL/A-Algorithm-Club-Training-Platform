import json
import io
from PIL import Image
from django.core.management import call_command
from datetime import date, datetime, time, timedelta
from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from .models import Semester, Submission, SubmissionPart, Team, TeamMembership, Week
from .services import approve_submission_parts, build_weeks, cleanup_semester


@override_settings(MEDIA_ROOT="/tmp/club-test-media")
class ClubApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="password-123")
        self.team = Team.objects.create(name="Test", code="TEST", created_by=self.user)
        self.member = TeamMembership.objects.create(user=self.user, team=self.team, display_name="林同学", role=TeamMembership.OWNER)
        self.semester = Semester.objects.create(team=self.team, name="测试学期", starts_on=date.today() - timedelta(days=7), ends_on=date.today() + timedelta(days=30))
        build_weeks(self.semester)
        self.client.force_login(self.user)
        self.client.session["team_id"] = self.team.id
        self.client.session.save()

    def test_join_and_login(self):
        client = Client()
        user = User.objects.create_user(username='new-member', password='password-123')
        client.force_login(user)
        response = client.post('/api/auth/join', data=json.dumps({'team_code':'TEST','name':'张同学'}), content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(TeamMembership.objects.get(user=user,team=self.team).role, TeamMembership.MEMBER)

    def test_members_weekly_score_and_contest_ac_problems(self):
        from .models import Problem
        week, other_week = list(self.semester.weeks.all()[:2])
        problem = Problem.objects.create(identity='test:ac', url='https://example.com/problem/ac')
        pending = Problem.objects.create(identity='test:pending', url='https://example.com/problem/pending')
        for target_week, target_problem, valid, status, points in [
            (week, problem, True, SubmissionPart.APPROVED, 1),
            (week, problem, True, SubmissionPart.APPROVED, 1),
            (week, pending, True, SubmissionPart.PENDING, 0),
            (week, pending, False, SubmissionPart.APPROVED, 10),
            (other_week, pending, True, SubmissionPart.APPROVED, 20),
        ]:
            submission = Submission.objects.create(team=self.team, member=self.member, semester=self.semester,
                                                   week=target_week, problem=target_problem, is_valid=valid)
            SubmissionPart.objects.create(submission=submission, kind=SubmissionPart.PROOF,
                                          status=status, points_awarded=points)
        from .models import ContestParticipation, ContestProblemProgress, PlatformBinding
        PlatformBinding.objects.create(user=self.user, platform='codeforces', account='owner')
        for key, account, target_week in [('current', 'owner', week), ('old', 'owner', other_week),
                                           ('unbound', 'previous', week)]:
            contest = ContestParticipation.objects.create(user=self.user, platform='codeforces', account=account,
                contest_key=key, title=key, url='https://example.com/contest',
                starts_at=target_week.starts_at, ends_at=target_week.ends_at)
            for label, accepted in [('A', True), ('B', True), ('C', False)]:
                ContestProblemProgress.objects.create(participation=contest, problem_key=label, label=label,
                    title=label, url='https://example.com/problem', accepted=accepted)
        with patch('club.views.active_semester', return_value=self.semester), patch('club.views.active_week', return_value=week):
            response = self.client.get('/api/members')
        self.assertEqual(response.status_code, 200)
        row = next(member for member in response.json()['members'] if member['id'] == self.member.id)
        # Two contest AC labels plus one distinct approved submission problem.
        self.assertEqual((row['score'], row['submissions'], row['ac_problems']), (2, 2, 3))

    def test_admin_invite_cannot_grant_management_role(self):
        user = User.objects.create_user(username='regular',password='password-123')
        self.client.force_login(user)
        response=self.client.post('/api/auth/join',data=json.dumps({'team_code':'TEST','name':'普通成员','admin_invite':'admin-me-2026','role':'admin'}),content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(TeamMembership.objects.get(user=user,team=self.team).role,'member')

    def test_login_and_logout_clears_team(self):
        client = Client()
        User.objects.create_user(username="caseaccount", password="password-123")
        response = client.post("/api/auth/login", data=json.dumps({"account": "caseaccount", "password": "password-123"}), content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        client.post("/api/auth/logout", data="{}", content_type="application/json")
        response = client.get("/api/me")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"], "请先登录")

    def test_csrf_endpoint_returns_json_token(self):
        client = Client()
        response = client.get("/api/csrf")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["csrfToken"])

    def test_register_validates_confirmation_and_preserves_case(self):
        client = Client()
        response = client.post("/api/auth/register", data=json.dumps({"grade": 0, "account": "CaseUser", "password": "password-123", "confirm_password": "different-123"}), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(username="CaseUser").exists())
        response = client.post("/api/auth/register", data=json.dumps({"grade": 0, "account": "CaseUser", "password": "password-123", "confirm_password": "password-123"}), content_type="application/json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(User.objects.filter(username="CaseUser").exists())
        response = client.post("/api/auth/register", data=json.dumps({"grade": 0, "account": "caseuser", "password": "password-123", "confirm_password": "password-123"}), content_type="application/json")
        self.assertEqual(response.status_code, 201, response.content)

    def test_submission_requires_proof_and_can_be_approved(self):
        response = self.client.post("/api/submissions", data={})
        self.assertEqual(response.status_code, 400)
        image = io.BytesIO()
        Image.new('RGB', (2, 2)).save(image, format='PNG')
        proof = SimpleUploadedFile('proof.png', image.getvalue(), content_type='image/png')
        response = self.client.post("/api/submissions", data={"week_id": self.semester.weeks.get(starts_at__lte=timezone.now(), ends_at__gt=timezone.now()).id, "proof": proof, "problem_url": "https://www.nowcoder.com/practice/d53b2057ae8a4eaf8155447f6b709361", "logic": "two pointers", "blog": "https://example.com"})
        self.assertEqual(response.status_code, 201)
        submission = self.member.submissions.first()
        approve_submission_parts(self.user, self.team, submission_ids=[submission.id])
        self.assertEqual(submission.parts.filter(status=SubmissionPart.APPROVED).count(), 3)




    def test_dashboard_exposes_live_stats(self):
        response = self.client.get("/api/dashboard")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("remainingSeconds", payload["current_week"])
        self.assertIn("totalWeeks", payload["semester"])
        self.assertIn("rank", payload["stats"])
        self.assertIn("pulse", payload)

    def test_weeks_start_on_monday_and_end_at_next_monday_midnight(self):
        weeks = list(self.semester.weeks.order_by("number"))
        self.assertGreaterEqual(len(weeks), 2)
        for week in weeks:
            self.assertEqual(timezone.localtime(week.starts_at).weekday(), 0)
            self.assertEqual(week.ends_at - week.starts_at, timedelta(days=7))
            self.assertEqual(timezone.localtime(week.ends_at).weekday(), 0)

    def test_build_weeks_preserves_history_until_explicit_repair(self):
        week = self.semester.weeks.order_by("number").first()
        legacy_start = week.starts_at - timedelta(days=1)
        week.starts_at = legacy_start
        week.ends_at = legacy_start + timedelta(days=7)
        week.save(update_fields=["starts_at", "ends_at"])
        build_weeks(self.semester)
        week.refresh_from_db()
        self.assertEqual(week.starts_at, legacy_start)
        call_command('repair_weeks', semester=self.semester.id, apply=True, stdout=io.StringIO())
        week.refresh_from_db()
        self.assertEqual(timezone.localtime(week.starts_at).weekday(), 0)
        self.assertEqual(week.ends_at - week.starts_at, timedelta(days=7))

    def test_build_weeks_repairs_legacy_trailing_week(self):
        trailing = Week.objects.create(
            semester=self.semester,
            number=99,
            starts_at=timezone.make_aware(datetime.combine(date.today(), time.min)),
            ends_at=timezone.make_aware(datetime.combine(date.today() + timedelta(days=7), time.min)),
        )
        call_command('repair_weeks', semester=self.semester.id, apply=True, stdout=io.StringIO())
        trailing.refresh_from_db()
        self.assertEqual(timezone.localtime(trailing.starts_at).weekday(), 0)
        self.assertEqual(trailing.ends_at - trailing.starts_at, timedelta(days=7))
