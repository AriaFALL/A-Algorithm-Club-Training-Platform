import importlib
import json

from django.apps import apps
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import connection, transaction, IntegrityError
from django.test import TestCase, TransactionTestCase, Client

from .models import Team, TeamMembership, Submission, SubmissionPart, SemesterMemberTotal, FileDeletion
from . import test_community as fixtures


class RoleTests(TestCase):
    image = fixtures.CommunityTests.image
    submit = fixtures.CommunityTests.submit
    post = fixtures.CommunityTests.post

    def setUp(self):
        fixtures.CommunityTests.setUp(self)
        self.root = User.objects.get(username='admin')
        self.admin_client = Client()
        self.admin_client.force_login(self.root)

    def test_default_admin_and_groups(self):
        self.assertTrue(self.root.check_password('admin123'))
        self.assertEqual(User.objects.filter(is_superuser=True).count(), 1)
        self.assertEqual(list(self.author.groups.values_list('name', flat=True)), ['普通用户组'])
        self.assertEqual(list(self.owner.groups.values_list('name', flat=True)), ['团队管理用户组'])
        self.assertFalse(self.owner.is_staff)
        with self.assertRaises(ValidationError):
            User.objects.create_superuser('second-admin',password='password-123')
        with self.assertRaises(ValidationError), transaction.atomic():
            self.root.delete()
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.filter(pk=self.author.pk).update(is_superuser=True)

    def test_only_admin_creates_teams_and_changes_configuration(self):
        data = {'team_name':'New','team_code':'NEW','join_password':'join-12345'}
        self.assertEqual(self.post('/api/auth/create-team',data).status_code,403)
        self.client.force_login(self.owner)
        self.assertEqual(self.post('/api/auth/create-team',data).status_code,403)
        self.assertEqual(self.client.get('/api/admin/team-settings').status_code,403)
        self.assertEqual(self.client.get('/api/management').status_code,200)
        response=self.admin_client.post('/api/auth/create-team',json.dumps(data),content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)
        team=Team.objects.get(code='NEW')
        self.assertEqual(team.created_by_id,self.root.pk)
        self.assertFalse(team.memberships.exists())
        self.assertTrue(team.semesters.exists())

    def test_admin_virtual_access_does_not_join_team(self):
        self.assertFalse(self.root.team_memberships.exists())
        self.assertEqual(self.admin_client.get('/api/dashboard').status_code,200)
        me=self.admin_client.get('/api/me').json()
        self.assertTrue(me['site_admin'])
        self.assertFalse(me['can_submit'])
        self.assertEqual(me['role'],'site_admin')
        self.assertFalse(self.root.team_memberships.exists())

    def test_grant_and_cancel_are_immediate_and_scoped(self):
        data={'team_id':self.team.pk,'account':self.author.username,'role':'admin'}
        self.assertEqual(self.post('/api/management/managers',data).status_code,403)
        result=self.admin_client.post('/api/management/managers',json.dumps(data),content_type='application/json')
        self.assertEqual(result.status_code,200,result.content)
        self.assertEqual(self.client.get('/api/admin/reports').status_code,200)
        self.assertEqual(list(self.author.groups.values_list('name',flat=True)),['团队管理用户组'])
        team=Team.objects.create(name='Other',code='OTHER',created_by=self.root)
        TeamMembership.objects.create(team=team,user=self.author,display_name='Author',role='member')
        self.post('/api/team/select',{'team_id':team.pk})
        self.assertEqual(self.client.get('/api/admin/reports').status_code,403)
        data['role']='member'
        self.assertEqual(self.admin_client.post('/api/management/managers',json.dumps(data),content_type='application/json').status_code,200)
        self.post('/api/team/select',{'team_id':self.team.pk})
        self.assertEqual(self.client.get('/api/admin/reports').status_code,403)
        self.assertEqual(list(self.author.groups.values_list('name',flat=True)),['普通用户组'])

    def test_appoint_can_add_registered_user_to_team(self):
        user=User.objects.create_user('not-joined')
        data={'team_id':self.team.pk,'account':user.username,'role':'admin'}
        result=self.admin_client.post('/api/management/managers',json.dumps(data),content_type='application/json')
        self.assertEqual(result.status_code,200,result.content)
        self.assertEqual(user.team_memberships.get(team=self.team).role,'admin')

    def test_direct_reject_does_not_require_report(self):
        submission=self.submit()
        endpoint=f'/api/submissions/{submission.pk}/reject'
        data={'version':1,'note':'题解不符合题目'}
        self.client.force_login(self.reader)
        self.assertEqual(self.post(endpoint,data).status_code,403)
        self.client.force_login(self.owner)
        detail=self.client.get(f'/api/problems/{self.problem.pk}/submissions').json()['submissions'][0]
        self.assertTrue(detail['can_reject'])
        self.assertEqual(self.post(endpoint,data).status_code,200)
        self.assertEqual(self.post(endpoint,data).status_code,409)
        submission.refresh_from_db()
        self.assertFalse(submission.is_valid)
        self.assertEqual(SemesterMemberTotal.objects.get(member=self.author_member).total_score,0)
        self.assertEqual(submission.review_logs.get().action,'direct_reject')

    def test_foreign_team_manager_cannot_reject_or_resolve(self):
        submission=self.submit()
        other=User.objects.create_user('foreign-manager')
        team=Team.objects.create(name='Other',code='OTHER',created_by=self.root)
        TeamMembership.objects.create(team=team,user=other,role='admin',display_name='Other manager')
        self.client.force_login(other)
        self.assertEqual(self.post(f'/api/submissions/{submission.pk}/reject',{'version':1,'note':'x'}).status_code,404)

    def test_admin_can_direct_reject_without_membership(self):
        submission=self.submit()
        result=self.admin_client.post(f'/api/submissions/{submission.pk}/reject',json.dumps({'version':1,'note':'管理员驳回'}),content_type='application/json')
        self.assertEqual(result.status_code,200,result.content)

    def test_team_deletion_requires_admin_and_code_and_manifests_files(self):
        submission=self.submit()
        endpoint=f'/api/management/teams/{self.team.pk}'
        data=json.dumps({'confirmation':self.team.code})
        self.assertEqual(self.client.delete(endpoint,data,content_type='application/json').status_code,403)
        self.assertEqual(self.admin_client.delete(endpoint,'{}',content_type='application/json').status_code,400)
        self.assertEqual(self.admin_client.delete(endpoint,data,content_type='application/json').status_code,200)
        self.assertFalse(Team.objects.filter(pk=self.team.pk).exists())
        self.assertFalse(Submission.objects.filter(pk=submission.pk).exists())
        self.assertTrue(FileDeletion.objects.exists())
        self.assertTrue(User.objects.filter(pk=self.author.pk).exists())
        self.assertEqual(list(self.owner.groups.values_list('name',flat=True)),['普通用户组'])

    def test_invite_and_registration_cannot_escalate(self):
        client=Client()
        data={'grade':0,'account':'newuser','password':'password-123','confirm_password':'password-123','is_superuser':True,'is_staff':True,'role':'admin'}
        self.assertEqual(client.post('/api/auth/register',json.dumps(data),content_type='application/json').status_code,201)
        user=User.objects.get(username='newuser')
        self.assertFalse(user.is_superuser or user.is_staff)
        self.assertEqual(client.get('/api/management').status_code,403)


class AccountResetTests(TransactionTestCase):
    def test_reset_removes_users_and_sessions_but_preserves_teams_and_configuration(self):
        root=User.objects.filter(username='admin').first() or User.objects.create_superuser('admin',password='old-password')
        previous=User.objects.create_user('previous-user',password='password-123')
        team=Team.objects.create(code='RESET',name='Keep team',created_by=previous,join_password_hash='keep-hash')
        TeamMembership.objects.create(team=team,user=previous,display_name='Remove me',role='admin')
        client=Client();client.force_login(previous)
        migration=importlib.import_module('club.migrations.0010_account_roles')
        with connection.schema_editor() as editor:
            migration.reset_member_accounts(apps,editor)
        self.assertEqual(list(User.objects.values_list('username',flat=True)),['admin'])
        self.assertTrue(User.objects.get(username='admin').check_password('admin123'))
        team.refresh_from_db()
        self.assertEqual(team.created_by_id,root.pk)
        self.assertEqual(team.join_password_hash,'keep-hash')
        self.assertFalse(TeamMembership.objects.exists())
        self.assertEqual(client.get('/api/me').status_code,401)
