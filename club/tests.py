import json
from datetime import date, datetime, time, timedelta
from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from .models import Arena, Semester, Submission, SubmissionPart, Team, TeamMembership, Week
from .services import approve_submission_parts, build_weeks, cleanup_semester


@override_settings(MEDIA_ROOT="/tmp/club-test-media")
class ClubApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="password-123")
        self.team = Team.objects.create(name="Test", code="TEST", join_password_hash=make_password("join-12345"), created_by=self.user)
        self.member = TeamMembership.objects.create(user=self.user, team=self.team, display_name="林同学", role=TeamMembership.OWNER)
        self.semester = Semester.objects.create(team=self.team, name="测试学期", starts_on=date.today() - timedelta(days=7), ends_on=date.today() + timedelta(days=30))
        build_weeks(self.semester)
        self.client.force_login(self.user)
        self.client.session["team_id"] = self.team.id
        self.client.session.save()

    def test_join_and_login(self):
        client = Client()
        response = client.post("/api/auth/join", data=json.dumps({"team_code": "TEST", "name": "张同学", "password": "password-123", "join_password": "join-12345"}), content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        joined = TeamMembership.objects.get(team=self.team, display_name="张同学")
        self.assertEqual(joined.role, TeamMembership.MEMBER)
        self.assertNotEqual(joined.user_id, self.user.id)

    def test_admin_invite_is_required_for_admin_role(self):
        self.team.admin_invite_hash = make_password("admin-123456")
        self.team.save(update_fields=["admin_invite_hash"])

        client = Client()
        response = client.post("/api/auth/join", data=json.dumps({"team_code": "TEST", "name": "普通成员", "password": "password-123", "join_password": "join-12345", "admin_invite": "wrong-code"}), content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        regular = TeamMembership.objects.get(team=self.team, display_name="普通成员")
        self.assertEqual(regular.role, TeamMembership.MEMBER)

        admin_client = Client()
        response = admin_client.post("/api/auth/join", data=json.dumps({"team_code": "TEST", "name": "管理员成员", "password": "password-123", "join_password": "join-12345", "admin_invite": "admin-123456"}), content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        elevated = TeamMembership.objects.get(team=self.team, display_name="管理员成员")
        self.assertEqual(elevated.role, TeamMembership.ADMIN)

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
        response = client.post("/api/auth/register", data=json.dumps({"account": "CaseUser", "password": "password-123", "confirm_password": "different-123"}), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(username="CaseUser").exists())
        response = client.post("/api/auth/register", data=json.dumps({"account": "CaseUser", "password": "password-123", "confirm_password": "password-123"}), content_type="application/json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(User.objects.filter(username="CaseUser").exists())
        response = client.post("/api/auth/register", data=json.dumps({"account": "caseuser", "password": "password-123", "confirm_password": "password-123"}), content_type="application/json")
        self.assertEqual(response.status_code, 201, response.content)

    def test_submission_requires_proof_and_can_be_approved(self):
        response = self.client.post("/api/submissions", data={})
        self.assertEqual(response.status_code, 400)
        proof = SimpleUploadedFile("proof.png", b"fake-image", content_type="image/png")
        response = self.client.post("/api/submissions", data={"proof": proof, "logic": "two pointers", "blog": "https://example.com"})
        self.assertEqual(response.status_code, 201)
        submission = self.member.submissions.first()
        approve_submission_parts(self.user, submission_ids=[submission.id])
        self.assertEqual(submission.parts.filter(status=SubmissionPart.APPROVED).count(), 3)

    def test_team_visibility_blocks_other_member_history(self):
        other_user = User.objects.create_user(username="other", password="password-123")
        other = TeamMembership.objects.create(user=other_user, team=self.team, display_name="周同学")
        self.client.force_login(other_user)
        self.client.session["team_id"] = self.team.id
        self.client.session.save()
        response = self.client.get(f"/api/members/{self.member.id}/history")
        self.assertEqual(response.status_code, 200)
        self.team.visibility_mode = Team.VISIBILITY_ADMIN
        self.team.save(update_fields=["visibility_mode"])
        response = self.client.get(f"/api/members/{self.member.id}/history")
        self.assertEqual(response.status_code, 403)

    def test_showcase_returns_only_approved_parts_and_hides_private_submissions(self):
        other_user = User.objects.create_user(username="showcase-member", password="password-123")
        other = TeamMembership.objects.create(user=other_user, team=self.team, display_name="展示成员")
        week = self.semester.weeks.first()
        submission = Submission.objects.create(team=self.team, member=other, semester=self.semester, week=week)
        SubmissionPart.objects.create(submission=submission, kind=SubmissionPart.PROOF, upload=SimpleUploadedFile("proof.png", b"proof", content_type="image/png"))
        SubmissionPart.objects.create(submission=submission, kind=SubmissionPart.LOGIC, text_content="approved logic", status=SubmissionPart.APPROVED, points_awarded=1)

        client = Client()
        client.force_login(other_user)
        client.session["team_id"] = self.team.id
        client.session.save()
        response = client.get("/api/showcase")
        self.assertEqual(response.status_code, 200)
        payload = response.json()["submissions"]
        self.assertEqual(len(payload), 1)
        self.assertEqual([part["kind"] for part in payload[0]["parts"]], [SubmissionPart.LOGIC])

        submission.visibility = Submission.VISIBILITY_PRIVATE
        submission.save(update_fields=["visibility"])
        self.assertEqual(client.get("/api/showcase").json()["submissions"], [])

    def test_arena_is_hidden_outside_open_window(self):
        now = timezone.now()
        Arena.objects.create(team=self.team, title="Future", opens_at=now + timedelta(hours=1), closes_at=now + timedelta(hours=2), is_published=True, created_by=self.user)
        response = self.client.get("/api/arena")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["arena"])

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

    def test_build_weeks_repairs_legacy_sunday_boundaries(self):
        week = self.semester.weeks.order_by("number").first()
        legacy_start = week.starts_at - timedelta(days=1)
        week.starts_at = legacy_start
        week.ends_at = legacy_start + timedelta(days=7)
        week.save(update_fields=["starts_at", "ends_at"])
        build_weeks(self.semester)
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
        build_weeks(self.semester)
        trailing.refresh_from_db()
        self.assertEqual(timezone.localtime(trailing.starts_at).weekday(), 0)
        self.assertEqual(trailing.ends_at - trailing.starts_at, timedelta(days=7))

    def test_admin_stats_list_members_who_missed_previous_week(self):
        previous_week = self.semester.weeks.order_by("number").first()
        previous_week.is_closed = True
        previous_week.save(update_fields=["is_closed"])
        other_user = User.objects.create_user(username="incomplete", password="password-123")
        other = TeamMembership.objects.create(user=other_user, team=self.team, display_name="未达标成员")
        response = self.client.get("/api/submissions")
        self.assertEqual(response.status_code, 200, response.content)
        stats = response.json()["stats"]
        self.assertEqual(stats["lastWeekNumber"], previous_week.number)
        incomplete = {item["id"]: item for item in stats["lastWeekIncompleteMembers"]}
        self.assertIn(other.id, incomplete)
        self.assertEqual(incomplete[other.id]["score"], 0)
        self.assertEqual(incomplete[other.id]["submissions"], 0)
        self.assertTrue(incomplete[other.id]["requiredBoth"])

    def test_visibility_action_persists_submission_visibility(self):
        week = self.semester.weeks.first()
        submission = Submission.objects.create(team=self.team, member=self.member, semester=self.semester, week=week)
        response = self.client.post(
            "/api/admin/submissions/bulk-approve",
            data=json.dumps({"submission_ids": [submission.id], "action": "visibility", "visibility": "private"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        submission.refresh_from_db()
        self.assertEqual(submission.visibility, Submission.VISIBILITY_PRIVATE)
