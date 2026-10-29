import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo
from django.contrib.auth.models import User
from django.test import TestCase, SimpleTestCase, TransactionTestCase
from .models import (Team, TeamMembership, UserProfile, PlatformBinding, ContestParticipation,
    ContestProblemProgress, ContestProblemClaim, CurrencyBalance, CheckinRecord,
    StreakReward, WeeklyStreakGrant, ShopItem, UserInventory, ContestSyncState)
from .grades import grade_on
from .contest_rewards import reward_for, claim_problems, REWARD_START
from .currency_services import settle_weekly_streak, makeup_checkin
from .contest_progress_sources import hydrate


class GradeTests(SimpleTestCase):
    def test_semester_boundaries_and_cap(self):
        p = SimpleNamespace(grade=0, grade_date=date(2026, 10, 29))
        for day, expected in [(date(2027,2,14),0),(date(2027,2,15),1),(date(2027,8,1),2),
                              (date(2028,2,15),3),(date(2028,8,1),4),(date(2030,1,1),4)]:
            self.assertEqual(grade_on(p,day),expected)
        self.assertIsNone(grade_on(None))


class ProgressTests(TestCase):
    def setUp(self):
        root = User.objects.get(username='admin')
        self.user = User.objects.create_user('progress-reader')
        self.team = Team.objects.create(name='Progress', code='PROGRESS', created_by=root, currency_enabled=True)
        self.member = TeamMembership.objects.create(team=self.team,user=self.user,display_name='Reader')
        self.profile = UserProfile.objects.create(user=self.user,grade=0,grade_date=date(2026,10,29))
        self.binding = PlatformBinding.objects.create(user=self.user,platform='leetcode',account='cn:reader')
        self.contest = ContestParticipation.objects.create(user=self.user,platform='leetcode',account='cn:reader',
            contest_key='weekly-contest-530',title='Weekly',url='https://leetcode.cn/contest/weekly-contest-530/',
            starts_at=REWARD_START,ends_at=REWARD_START+timedelta(hours=2),detail_complete=True)
        self.problem = ContestProblemProgress.objects.create(participation=self.contest,problem_key='sample',label='Q1',
            title='Sample',url='https://leetcode.cn/problems/sample/',difficulty=599,difficulty_source='fixture',
            accepted=True,official_ac=True,accepted_at=REWARD_START+timedelta(minutes=5))
        self.client.force_login(self.user)
        self.clock = patch('django.utils.timezone.now',return_value=REWARD_START+timedelta(days=10))
        self.clock.start();self.addCleanup(self.clock.stop)

    def test_reward_boundaries_grade_and_zero(self):
        for grade, values in [(0,[(599,1),(600,2),(1199,2),(1200,3)]),(1,[(999,1),(1000,2),(1499,2),(1500,3)])]:
            self.profile.grade=grade;self.profile.save()
            for difficulty, expected in values:
                self.problem.difficulty=difficulty
                self.assertEqual(reward_for(self.problem,self.member)[0],expected)
        self.team.problem_rewards={'beginner':[0,0,0],'experienced':[0,0,0]};self.team.save()
        self.assertEqual(reward_for(self.problem,self.member)[0],0)

    def test_cutoff_known_outside_time_and_relaxed_unknown(self):
        self.contest.starts_at=REWARD_START-timedelta(seconds=1)
        self.assertEqual(reward_for(self.problem,self.member)[0],0)

        self.contest.starts_at=REWARD_START
        self.problem.accepted_at=self.contest.ends_at
        self.assertEqual(reward_for(self.problem,self.member)[0],0)
        self.problem.accepted_at=None
        self.assertEqual(reward_for(self.problem,self.member)[0],1)
        self.problem.difficulty=None
        self.assertEqual(reward_for(self.problem,self.member)[0],1)
        self.problem.accepted=False
        self.assertEqual(reward_for(self.problem,self.member)[0],0)

    def test_demo_clock_is_restricted_to_explicit_fixture_team(self):
        with patch('django.utils.timezone.now',return_value=REWARD_START-timedelta(days=1)):
            self.assertEqual(reward_for(self.problem,self.member)[0],0)
            self.contest.source_data={'demo':True,'demo_team_id':self.team.pk}
            self.assertEqual(reward_for(self.problem,self.member)[0],1)
            self.contest.source_data={'demo':True,'demo_team_id':self.team.pk+1}
            self.assertEqual(reward_for(self.problem,self.member)[0],0)
        self.assertEqual(reward_for(self.problem,self.member)[0],0)

    def test_exactly_once_individual_then_batch_and_other_user(self):
        second=ContestProblemProgress.objects.create(participation=self.contest,problem_key='second',label='Q2',title='Two',accepted_at=REWARD_START+timedelta(minutes=10),
            accepted=True,official_ac=True,difficulty=1200,difficulty_source='fixture')
        result=claim_problems(self.member,[self.problem.pk])
        self.assertEqual(result['total'],1)
        self.assertEqual(claim_problems(self.member,[self.problem.pk])['total'],0)
        self.assertEqual(claim_problems(self.member)['total'],3)
        self.assertEqual(CurrencyBalance.objects.get(member=self.member).balance,4)
        self.assertEqual(ContestProblemClaim.objects.count(),2)
        other=User.objects.create_user('other-progress')
        outsider=TeamMembership.objects.create(user=other,team=self.team,display_name='Other')
        self.assertEqual(claim_problems(outsider,[second.pk])['total'],0)

    def test_binding_change_and_missing_grade_block_claim(self):
        self.binding.account='cn:different';self.binding.save()
        self.assertEqual(claim_problems(self.member)['total'],0)
        self.binding.account='cn:reader';self.binding.save()
        self.profile.grade=None;self.profile.save()
        self.assertEqual(claim_problems(self.member)['total'],0)

    def test_leaving_and_rejoining_team_does_not_reset_claim(self):
        self.assertEqual(claim_problems(self.member)['total'],1)
        self.member.delete()
        member=TeamMembership.objects.create(team=self.team,user=self.user,display_name='Rejoined')
        self.assertEqual(claim_problems(member)['total'],0)
        self.assertEqual(ContestProblemClaim.objects.count(),1)

    def test_api_history_not_limited_by_calendar_window_and_permissions(self):
        self.contest.starts_at=REWARD_START-timedelta(days=800);self.contest.ends_at=self.contest.starts_at+timedelta(hours=2);self.contest.save()
        data=self.client.get('/api/contests/progress').json()
        self.assertEqual(len(data['contests']),1)
        self.assertFalse(data['contests'][0]['problems'][0]['claimable'])
        self.assertEqual(self.client.post('/api/contests/claim',json.dumps({'ids':'bad'}),content_type='application/json').status_code,400)
        self.client.force_login(User.objects.get(username='admin'))
        self.assertEqual(self.client.get('/api/contests/progress').status_code,403)

    def test_grade_fill_once_and_admin_reward_configuration(self):
        self.profile.grade=None;self.profile.save()
        self.assertEqual(self.client.post('/api/profile',{'name':'Reader','grade':0}).status_code,400)
        self.assertEqual(self.client.post('/api/profile',{'name':'Reader','grade':3}).status_code,400)
        self.profile.refresh_from_db();self.assertIsNone(self.profile.grade)
        payload={'team_id':self.team.pk,'problem_rewards':{'beginner':[2,4,6],'experienced':[1,2,3]}}
        self.assertEqual(self.client.post('/api/currency/admin/config',json.dumps(payload),content_type='application/json').status_code,403)
        self.client.force_login(User.objects.get(username='admin'))
        self.assertEqual(self.client.post('/api/currency/admin/config',json.dumps(payload),content_type='application/json').status_code,200)
        result=self.client.get('/api/currency/admin/config',{'team_id':self.team.pk}).json()
        self.assertEqual(result['problem_rewards'],payload['problem_rewards'])
        payload['problem_rewards']['beginner']=[-1,2,3]
        self.assertEqual(self.client.post('/api/currency/admin/config',json.dumps(payload),content_type='application/json').status_code,400)

    def test_sync_only_enqueues_once_and_stale_results_ignored(self):
        from .tasks import hydrate_contest_progress
        with patch('club.tasks.discover_contest_progress.delay') as dispatch, self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.client.post('/api/contests/progress').status_code,202)
            self.assertEqual(self.client.post('/api/contests/progress').status_code,202)
        dispatch.assert_called_once()
        with patch('club.contest_progress_sources.hydrate') as source:
            hydrate_contest_progress(self.contest.pk,'00000000-0000-0000-0000-000000000000')
            source.assert_not_called()

    def test_sync_failure_retains_verified_progress(self):
        from .tasks import hydrate_contest_progress
        from .platform_sync import SyncError
        state=ContestSyncState.objects.create(user=self.user,status='pending',remaining=1,total=1)
        with patch('club.contest_progress_sources.hydrate',side_effect=SyncError('访问受限')):
            hydrate_contest_progress(self.contest.pk,str(state.token))
        self.problem.refresh_from_db();self.contest.refresh_from_db();state.refresh_from_db()
        self.assertTrue(self.problem.accepted)
        self.assertTrue(self.contest.detail_complete)
        self.assertEqual(self.contest.sync_error,'访问受限')
        self.assertEqual(state.status,'ready')


class WeeklyRewardTests(TestCase):
    def setUp(self):
        root=User.objects.get(username='admin')
        self.team=Team.objects.create(name='Weeks',code='WEEKREWARD',created_by=root,currency_enabled=True)
        user=User.objects.create_user('weekly-member')
        self.member=TeamMembership.objects.create(team=self.team,user=user,display_name='Week')
        StreakReward.objects.create(team=self.team,days=3,reward=1)
        StreakReward.objects.create(team=self.team,days=7,reward=2)
        self.monday=date(2026,10,19)

    def checkin(self,offset):
        CheckinRecord.objects.create(team=self.team,member=self.member,checkin_date=self.monday+timedelta(days=offset))

    def test_threshold_once_per_week_and_no_cross_week_run(self):
        for offset in [0,1,2,4,5,6]:self.checkin(offset)
        self.assertEqual(settle_weekly_streak(self.member,self.monday),1)
        self.assertEqual(settle_weekly_streak(self.member,self.monday),0)
        self.checkin(7)
        self.assertEqual(settle_weekly_streak(self.member,self.monday+timedelta(days=7)),0)
        self.checkin(8);self.checkin(9)
        self.assertEqual(settle_weekly_streak(self.member,self.monday+timedelta(days=9)),1)

    def test_opening_makeup_does_not_grant_streak_before_submission(self):
        for offset in [0,1,2,4,5,6]:self.checkin(offset)
        settle_weekly_streak(self.member,self.monday)
        item=ShopItem.objects.create(team=self.team,name='Ticket',item_type='makeup_ticket',price=3)
        inventory=UserInventory.objects.create(team=self.team,member=self.member,item=item,quantity=1)
        from .models import Semester
        from django.utils import timezone
        Semester.objects.create(team=self.team,name='Current',starts_on=self.monday,
            ends_on=max(timezone.localdate(),self.monday)+timedelta(days=30))
        result=makeup_checkin(self.member,self.monday+timedelta(days=3))
        self.assertFalse(result['completed'])
        self.assertEqual(WeeklyStreakGrant.objects.filter(member=self.member).count(),1)
        self.assertEqual(settle_weekly_streak(self.member,self.monday),0)
        inventory.refresh_from_db();self.assertEqual(inventory.quantity,0)



class EvidenceTests(SimpleTestCase):
    def test_luogu_timestamp_units_verdict_and_account(self):
        from .contest_progress_sources import luogu_ac_times
        from .platform_sync import SyncError
        remote=Mock()
        remote.json.side_effect=[{'code':200,'data':{'records':{'result':[
            {'id':3,'status':12,'submitTime':1700000020000,'problem':{'pid':'P1'},'user':{'uid':8}},
            {'id':2,'status':14,'submitTime':1700000010,'problem':{'pid':'P2'},'user':{'uid':8}},
            {'id':1,'status':12,'problem':{'pid':'P3'},'user':{'uid':8}}]}}},
            {'currentData':{'records':{'result':[]}}}]
        with patch('club.contest_progress_sources.time.sleep'):
            rows=luogu_ac_times(remote,'8','_uid=7; __client_id=test',1699999990)
        self.assertEqual(rows,{'P1':[1700000020.0],'P3':[None]})
        with self.assertRaises(SyncError):
            luogu_ac_times(remote,'8','_uid=7',0)

    def test_atcoder_uses_original_task_roster_not_reassigned_catalog(self):
        remote=Mock()
        remote.text.return_value='<table><tbody><tr><td><a href="/contests/abc400/tasks/abc400_a">A</a></td><td>Party</td></tr><tr><td><a href="/contests/abc400/tasks/abc400_b">B</a></td><td>Sum</td></tr></tbody></table>'
        remote.json.return_value=[{'contest_id':'abc400','problem_id':'abc400_a','epoch_second':REWARD_START.timestamp()+10,'result':'AC'}]
        contest=SimpleNamespace(platform='atcoder',contest_key='abc400',account='reader',url='https://atcoder.jp/contests/abc400',
            starts_at=REWARD_START,ends_at=REWARD_START+timedelta(hours=2))
        with patch('club.contest_progress_sources.cached',return_value={'abc400_a':{'difficulty':400}}):
            rows,error=hydrate(remote,contest)
        self.assertEqual([r['label'] for r in rows],['A','B'])
        self.assertTrue(rows[0]['official_ac']);self.assertFalse(rows[1]['accepted'])

    def test_leetcode_matches_region_and_rejects_out_of_window(self):
        remote=Mock()
        contest=SimpleNamespace(platform='leetcode',contest_key='weekly-contest-530',account='cn:reader',
            starts_at=REWARD_START,ends_at=REWARD_START+timedelta(hours=2),source_data={'rank':1})
        start=REWARD_START.timestamp()
        remote.json.side_effect=[{'contest':{'start_time':start,'duration':7200},'questions':[
            {'question_id':1,'title_slug':'sample','title':'Sample'}, {'question_id':2,'title_slug':'two','title':'Two'}]},
            {'total_rank':[{'user_slug':'reader','data_region':'US'},{'user_slug':'reader','data_region':'CN'}],
             'submissions':[{'1':{'status':10,'date':start+10}}, {'1':{'status':10,'date':start+7200},'2':{'status':10,'date':start+10}}]}]
        with patch('club.contest_progress_sources.cache.get',return_value={'sample':500,'two':1500}):
            rows,error=hydrate(remote,contest)
        self.assertFalse(rows[0]['official_ac']);self.assertTrue(rows[1]['official_ac'])
        self.assertEqual(rows[1]['difficulty'],1500)


class ConcurrentClaimTests(TransactionTestCase):
    def test_simultaneous_single_and_bulk_claim_only_credit_once(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import close_old_connections
        user=User.objects.create_user('concurrent-claim-user')
        team=Team.objects.create(name='Concurrent',code='CONCURRENTCLAIM',created_by=user,currency_enabled=True)
        member=TeamMembership.objects.create(team=team,user=user,display_name='Concurrent')
        UserProfile.objects.create(user=user,grade=0,grade_date=date(2026,10,29))
        PlatformBinding.objects.create(user=user,platform='leetcode',account='cn:concurrent')
        contest=ContestParticipation.objects.create(user=user,platform='leetcode',account='cn:concurrent',
            contest_key='concurrent',title='Concurrent',starts_at=REWARD_START,ends_at=REWARD_START+timedelta(hours=2),detail_complete=True)
        problem=ContestProblemProgress.objects.create(participation=contest,problem_key='q1',label='Q1',title='One',
            accepted=True,official_ac=True,accepted_at=REWARD_START+timedelta(minutes=10),difficulty=600,difficulty_source='fixture')
        barrier=Barrier(2)
        def run(ids):
            close_old_connections()
            try:
                local=TeamMembership.objects.get(pk=member.pk)
                barrier.wait(timeout=10)
                return claim_problems(local,ids)['total']
            finally:
                close_old_connections()
        with patch('django.utils.timezone.now',return_value=REWARD_START+timedelta(days=1)), ThreadPoolExecutor(2) as pool:
            results=list(pool.map(run,[[problem.pk],None]))
        self.assertEqual(sorted(results),[0,2])
        self.assertEqual(CurrencyBalance.objects.get(member=member).balance,2)
        self.assertEqual(ContestProblemClaim.objects.count(),1)
