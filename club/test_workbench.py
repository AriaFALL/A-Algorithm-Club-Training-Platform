import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.utils import timezone

from .models import Team, TeamMembership, Semester, SemesterMemberTotal, Submission, SubmissionPart, SubmissionReport, Problem, ParserSettings
from . import test_community as fixtures


class WorkbenchTests(TestCase):
    image = fixtures.CommunityTests.image
    submit = fixtures.CommunityTests.submit
    post = fixtures.CommunityTests.post

    def setUp(self):
        fixtures.CommunityTests.setUp(self)
        self.root = User.objects.get(username='admin')
        self.admin_client = Client(); self.admin_client.force_login(self.root)

    def test_grouped_members_and_archived_counts(self):
        self.submit()
        old = Semester.objects.create(team=self.team, name='Archive', starts_on=self.semester.starts_on,
            ends_on=self.semester.ends_on, is_active=False, archived_at=timezone.now())
        SemesterMemberTotal.objects.create(member=self.author_member, semester=old, total_submissions=7)
        other = Team.objects.create(name='Another', code='OTHER', created_by=self.root)
        data = self.admin_client.get('/api/management').json()
        self.assertEqual(len(data['teams']), 2)
        row = next(m for t in data['teams'] for m in t['member_rows'] if m['id'] == self.author_member.pk)
        self.assertEqual(row['submissions'], 8)
        self.client.force_login(self.owner)
        data = self.client.get('/api/management').json()
        self.assertEqual([t['id'] for t in data['teams']], [self.team.pk])
        self.assertEqual(data['users'], [])
        self.assertFalse(data['site_admin'])

    def test_kick_preserves_history_and_revokes_access(self):
        submission = self.submit()
        self.client.force_login(self.owner)
        path = f'/api/management/teams/{self.team.pk}/members/{self.author_member.pk}'
        result = self.client.delete(path, json.dumps({'confirmation':self.author_member.display_name}), content_type='application/json')
        self.assertEqual(result.status_code,200,result.content)
        self.author_member.refresh_from_db()
        self.assertFalse(self.author_member.is_active)
        self.assertTrue(Submission.objects.filter(pk=submission.pk).exists())
        self.client.force_login(self.author)
        self.assertEqual(self.client.get('/api/showcase').status_code,403)
        self.assertEqual(self.client.get('/api/management').status_code,403)
        self.assertTrue(User.objects.filter(pk=self.author.pk).exists())

    def test_kick_permissions_and_stale_confirmation(self):
        self.client.force_login(self.owner)
        own = f'/api/management/teams/{self.team.pk}/members/{self.owner_member.pk}'
        self.assertEqual(self.client.delete(own,json.dumps({'confirmation':self.owner_member.display_name}),content_type='application/json').status_code,403)
        third = User.objects.create_user('second-manager')
        manager = TeamMembership.objects.create(team=self.team,user=third,display_name='Second',role='admin')
        path = f'/api/management/teams/{self.team.pk}/members/{manager.pk}'
        payload = json.dumps({'confirmation':manager.display_name})
        self.assertEqual(self.client.delete(path,payload,content_type='application/json').status_code,403)
        self.assertEqual(self.admin_client.delete(path,'{}',content_type='application/json').status_code,409)
        self.assertEqual(self.admin_client.delete(path,payload,content_type='application/json').status_code,200)
        third.refresh_from_db()
        self.assertEqual(list(third.groups.values_list('name',flat=True)),['普通用户组'])

    def test_foreign_team_kick_denied(self):
        other = Team.objects.create(name='Another',code='OTHER',created_by=self.root)
        membership = TeamMembership.objects.create(team=other,user=self.reader,display_name='Reader')
        self.client.force_login(self.owner)
        path=f'/api/management/teams/{other.pk}/members/{membership.pk}'
        self.assertEqual(self.client.delete(path,json.dumps({'confirmation':'Reader'}),content_type='application/json').status_code,403)

    def test_parser_configuration_masking_and_blank_key_preserves(self):
        data={'mode':'smart','enabled':True,'base_url':'https://api.example.com/v1','model':'test-model','api_key':'private-test-key'}
        response=self.admin_client.put('/api/management/parser',json.dumps(data),content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)
        before=ParserSettings.objects.get(pk=1).encrypted_key
        self.assertNotIn('private-test-key',before)
        response=self.admin_client.get('/api/management/parser')
        self.assertTrue(response.json()['has_key'])
        self.assertNotIn('private-test-key',response.content.decode())
        self.assertNotIn(before,response.content.decode())
        data['api_key']=''; data['mode']='auto'
        self.admin_client.put('/api/management/parser',json.dumps(data),content_type='application/json')
        self.assertEqual(ParserSettings.objects.get(pk=1).encrypted_key,before)
        data['mode']='invalid'
        self.assertEqual(self.admin_client.put('/api/management/parser',json.dumps(data),content_type='application/json').status_code,400)
        self.assertEqual(ParserSettings.objects.get(pk=1).mode,'auto')
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get('/api/management/parser').status_code,403)
        self.assertEqual(self.client.put('/api/management/parser',json.dumps(data),content_type='application/json').status_code,403)

    def test_pending_titles_manual_save_and_selected_retry(self):
        Problem.objects.all().delete()
        self.assertEqual(self.admin_client.get('/api/management/problems').json()['problems'],[])
        problem=Problem.objects.create(identity='pending',url='https://example.com/qa',status='failed')
        self.assertEqual(len(self.admin_client.get('/api/management/problems').json()['problems']),1)
        response=self.admin_client.patch(f'/api/management/problems/{problem.pk}',json.dumps({'title':'正确题名'}),content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)
        problem.refresh_from_db()
        self.assertEqual((problem.status,problem.generation),('manual',1))
        self.assertEqual(self.admin_client.get('/api/management/problems').json()['problems'],[])
        with patch('club.tasks.resolve_problem.apply_async') as dispatch, self.captureOnCommitCallbacks(execute=True):
            response=self.admin_client.post(f'/api/management/problems/{problem.pk}/retry',json.dumps({'mode':'ai'}),content_type='application/json')
        self.assertEqual(response.status_code,202)
        self.assertEqual(dispatch.call_args.kwargs['args'][2],'ai')
        problem.refresh_from_db()
        self.assertEqual(problem.title,'正确题名')
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get('/api/management/problems').status_code,200)
        self.assertEqual(self.client.get('/api/management/problems').json()['problems'],[])

    def test_parser_test_uses_saved_configuration_and_requires_root(self):
        with patch('club.problem_parser.ai_title',return_value='测试题名') as ai:
            response=self.admin_client.post('/api/management/parser/test')
            self.assertEqual(response.json()['title'],'测试题名')
            ai.assert_called_once()
        self.client.force_login(self.owner)
        with patch('club.problem_parser.ai_title') as ai:
            self.assertEqual(self.client.post('/api/management/parser/test').status_code,403)
            ai.assert_not_called()

    def test_root_reports_cover_all_teams_without_switching(self):
        first=self.submit()
        SubmissionReport.objects.create(submission=first,version=1,reporter=self.reader)
        other=Team.objects.create(name='Other',code='OTHER',created_by=self.root)
        semester=Semester.objects.create(team=other,name='Other term',starts_on=self.semester.starts_on,ends_on=self.semester.ends_on)
        from .services import build_weeks
        build_weeks(semester)
        member=TeamMembership.objects.create(team=other,user=self.author,display_name='Author')
        second=Submission.objects.create(team=other,semester=semester,week=semester.weeks.first(),member=member,problem=self.problem)
        SubmissionPart.objects.create(submission=second,kind='logic',text_content='test',status='approved')
        SubmissionReport.objects.create(submission=second,version=1,reporter=self.reader)
        rows=self.admin_client.get('/api/admin/reports').json()['submissions']
        self.assertEqual({r['id'] for r in rows},{first.pk,second.pk})
        response=self.admin_client.post(f'/api/admin/reports/{second.pk}/resolve',json.dumps({'version':1,'action':'dismiss'}),content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)
        self.client.force_login(self.owner)
        rows=self.client.get('/api/admin/reports').json()['submissions']
        self.assertEqual([r['id'] for r in rows],[first.pk])

    def test_global_manager_nav_flag_remains_in_other_membership(self):
        other=Team.objects.create(name='Other',code='OTHER',created_by=self.root)
        TeamMembership.objects.create(team=other,user=self.owner,display_name='Owner ordinary',role='member')
        self.client.force_login(self.owner)
        self.post('/api/team/select',{'team_id':other.pk})
        me=self.client.get('/api/me').json()
        self.assertTrue(me['is_team_manager'])
        self.assertFalse(me['can_manage_current'])
        self.assertEqual(me['managed_teams'][0]['team_id'],self.team.pk)
        self.assertEqual(self.client.get('/api/management').status_code,403)

    def test_team_settings_available_from_frontend_only_for_root(self):
        endpoint=f'/api/management/teams/{self.team.pk}/settings'
        data=self.admin_client.get(endpoint).json()
        payload={'name':'Updated','code':self.team.code,'min_score':3,
            'min_submissions':2,'screenshot_points':1,'logic_points':2,'blog_points':3,'require_both':False}
        self.assertEqual(self.admin_client.put(endpoint,json.dumps(payload),content_type='application/json').status_code,200)
        self.semester.refresh_from_db()
        self.assertEqual((self.semester.min_score,self.semester.logic_points),(3,2))
        self.assertIsNone(self.semester.cleanup_at)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(endpoint).status_code,403)

    def test_legacy_workbench_redirects_to_main_and_no_team_root_still_has_access(self):
        self.assertRedirects(self.admin_client.get('/manage.html'),'/?view=admin',fetch_redirect_response=False)
        Team.objects.all().delete()
        me=self.admin_client.get('/api/me').json()
        self.assertIsNone(me['team'])
        self.assertTrue(me['can_manage_current'])
        self.assertEqual(self.admin_client.get('/api/management').status_code,200)
        self.assertEqual(self.admin_client.get('/api/admin/reports').status_code,200)

    def test_member_cards_receive_actions_for_viewer_role(self):
        def rows(client):
            return {m['id']: m for m in client.get('/api/members').json()['members']}
        root_rows = rows(self.admin_client)
        self.assertTrue(root_rows[self.author_member.pk]['can_kick'])
        self.assertTrue(root_rows[self.author_member.pk]['can_manage_role'])
        self.assertEqual(root_rows[self.author_member.pk]['account'],self.author.username)
        self.assertTrue(root_rows[self.owner_member.pk]['can_kick'])
        self.client.force_login(self.owner)
        manager_rows = rows(self.client)
        self.assertTrue(manager_rows[self.author_member.pk]['can_kick'])
        self.assertFalse(manager_rows[self.author_member.pk]['can_manage_role'])
        self.assertFalse(manager_rows[self.owner_member.pk]['can_kick'])
        self.assertEqual(manager_rows[self.author_member.pk]['account'],'')
        self.client.force_login(self.reader)
        ordinary_rows = rows(self.client)
        self.assertTrue(all(not m['can_kick'] and not m['can_manage_role'] for m in ordinary_rows.values()))

    def test_team_manager_can_process_only_referenced_problem_titles(self):
        self.submit()
        foreign = Problem.objects.create(identity='foreign',url='https://example.com/foreign',status='failed')
        self.client.force_login(self.owner)
        items=self.client.get('/api/management/problems').json()['problems']
        self.assertEqual([p['id'] for p in items],[self.problem.pk])
        response=self.client.patch(f'/api/management/problems/{self.problem.pk}',json.dumps({'title':'团队补填题名'}),content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)
        self.problem.refresh_from_db()
        self.assertEqual((self.problem.title,self.problem.status,self.problem.generation),('团队补填题名','manual',1))
        self.assertEqual(self.client.patch(f'/api/management/problems/{foreign.pk}',json.dumps({'title':'越权'}),content_type='application/json').status_code,404)
        with patch('club.tasks.resolve_problem.apply_async') as dispatch, self.captureOnCommitCallbacks(execute=True):
            response=self.client.post(f'/api/management/problems/{self.problem.pk}/retry',json.dumps({'mode':'auto'}),content_type='application/json')
        self.assertEqual(response.status_code,202,response.content)
        self.assertEqual(dispatch.call_args.kwargs['args'][2],'auto')
        self.assertEqual(self.client.post(f'/api/management/problems/{foreign.pk}/retry',json.dumps({'mode':'ai'}),content_type='application/json').status_code,404)
        self.assertEqual(self.client.get('/api/management/parser').status_code,403)

    def test_title_permission_revocation_and_current_team_scope(self):
        self.submit()
        other=Team.objects.create(name='Other',code='SCOPE',created_by=self.root)
        TeamMembership.objects.create(team=other,user=self.owner,display_name='Other manager',role='admin')
        self.client.force_login(self.owner)
        self.post('/api/team/select',{'team_id':other.pk})
        self.assertEqual(self.client.get('/api/management/problems').json()['problems'],[])
        endpoint=f'/api/management/problems/{self.problem.pk}'
        self.assertEqual(self.client.patch(endpoint,json.dumps({'title':'跨团队'}),content_type='application/json').status_code,404)
        self.post('/api/team/select',{'team_id':self.team.pk})
        self.owner_member.role='member'; self.owner_member.save()
        self.assertEqual(self.client.get('/api/management/problems').status_code,403)
        self.assertEqual(self.client.patch(endpoint,json.dumps({'title':'已撤权'}),content_type='application/json').status_code,403)
