from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth.models import User
from .models import Team,TeamMembership,CheckinRecord,PlatformBinding,CurrencyBalance,Submission
from . import test_community as fixtures

class RankingTests(TestCase):
    setUp=fixtures.CommunityTests.setUp

    def rows(self,scope,platform='codeforces'):
        response=self.client.get('/api/leaderboard',{'scope':scope,'platform':platform})
        self.assertEqual(response.status_code,200,response.content)
        return response.json()['rows']

    def test_checkin_union_includes_makeup_and_breaks_at_missing_day(self):
        today=timezone.localdate()
        for offset in [0,1,2]:
            CheckinRecord.objects.create(team=self.team,member=self.author_member,checkin_date=today-timedelta(days=offset),is_makeup=offset==2)
        CheckinRecord.objects.create(team=self.team,member=self.owner_member,checkin_date=today-timedelta(days=3))
        # A valid submission counts as a signed-in day, with no double count.
        Submission.objects.create(team=self.team,member=self.author_member,semester=self.semester,week=self.week,problem=self.problem,record_date=today)
        rows=self.rows('checkin')
        self.assertEqual(rows[0]['memberId'],self.author_member.pk)
        self.assertEqual(rows[0]['value'],3)
        self.assertEqual(rows[0]['rank'],1)
        self.assertTrue(rows[0]['isCurrent'])
        self.assertTrue(all(r['value']==0 for r in rows[1:]))
        self.assertTrue(all(r['rank']==2 for r in rows[1:]))

    def test_wealth_uses_current_team_balance_including_zero(self):
        CurrencyBalance.objects.create(team=self.team,member=self.author_member,balance=12)
        CurrencyBalance.objects.create(team=self.team,member=self.owner_member,balance=24)
        rows=self.rows('wealth')
        self.assertEqual([r['value'] for r in rows],[24,12,0])
        CurrencyBalance.objects.filter(member=self.author_member).update(balance=30)
        self.assertEqual(self.rows('wealth')[0]['memberId'],self.author_member.pk)
        self.semester.delete()
        self.assertEqual(self.rows('wealth')[0]['value'],30)

    def test_rating_only_bound_members_and_platform_regions_are_separate(self):
        PlatformBinding.objects.create(user=self.author,platform='codeforces',account='author',snapshot={'rating':1800})
        binding=PlatformBinding.objects.create(user=self.owner,platform='codeforces',account='owner',snapshot={'rating':2100})
        rows=self.rows('rating')
        self.assertEqual([r['value'] for r in rows],[2100,1800])
        binding.snapshot={'rating':None};binding.save()
        rows=self.rows('rating')
        self.assertEqual(rows[0]['value'],1800)
        self.assertIsNone(rows[-1]['rank'])
        PlatformBinding.objects.create(user=self.author,platform='leetcode',account='cn:author',snapshot={'rating':1900})
        PlatformBinding.objects.create(user=self.owner,platform='leetcode',account='owner',snapshot={'rating':2300})
        self.assertEqual([r['memberId'] for r in self.rows('rating','leetcode_cn')],[self.author_member.pk])
        self.assertEqual([r['memberId'] for r in self.rows('rating','leetcode_us')],[self.owner_member.pk])
        self.assertEqual(self.rows('rating','atcoder'),[])

    def test_wealth_excludes_current_senior_grade_including_automatic_promotion(self):
        from datetime import date
        from unittest.mock import patch
        from .models import UserProfile
        UserProfile.objects.create(user=self.author, grade=4, grade_date=date(2026, 7, 31))
        UserProfile.objects.create(user=self.owner, grade=3, grade_date=date(2026, 7, 31))
        CurrencyBalance.objects.create(team=self.team, member=self.author_member, balance=100)
        CurrencyBalance.objects.create(team=self.team, member=self.owner_member, balance=200)
        with patch('club.grades.timezone.localdate', return_value=date(2026, 7, 31)):
            rows = self.rows('wealth')
            self.assertEqual(rows[0]['memberId'], self.owner_member.pk)
            self.assertNotIn(self.author_member.pk, [r['memberId'] for r in rows])
        with patch('club.grades.timezone.localdate', return_value=date(2026, 8, 1)):
            rows = self.rows('wealth')
            self.assertNotIn(self.owner_member.pk, [r['memberId'] for r in rows])
            self.assertTrue(all(r['rank'] == 1 for r in rows))
            self.assertIn(self.author_member.pk, [r['memberId'] for r in self.rows('solved')])
        self.assertEqual(CurrencyBalance.objects.get(member=self.author_member).balance, 100)

    def test_scope_permissions_and_inactive_members(self):
        self.author_member.is_active=False;self.author_member.save()
        self.client.force_login(self.reader)
        self.assertNotIn(self.author_member.pk,[r['memberId'] for r in self.rows('checkin')])
        self.assertEqual(self.client.get('/api/leaderboard?scope=unknown').status_code,400)
        self.assertEqual(self.client.get('/api/leaderboard?scope=rating&platform=unknown').status_code,400)
        self.assertEqual(self.client.post('/api/leaderboard').status_code,405)
        user=User.objects.create_user('ranking-outsider')
        self.client.force_login(user)
        self.assertEqual(self.client.get('/api/leaderboard').status_code,403)
        self.client.logout()
        self.assertEqual(self.client.get('/api/leaderboard').status_code,401)

    def test_solved_lifetime_survives_cleanup_sync_and_semester_deletion(self):
        from .models import ContestParticipation, ContestProblemProgress, SubmissionPart, SolvedProblemCredit
        from .services import cleanup_semester
        PlatformBinding.objects.create(user=self.author, platform='codeforces', account='author')
        contest = ContestParticipation.objects.create(user=self.author, platform='codeforces', account='author',
            contest_key='123', title='Contest', url='https://example.com/contest',
            starts_at=self.week.starts_at, ends_at=self.week.ends_at)
        for label in ['A', 'B']:
            ContestProblemProgress.objects.create(participation=contest, problem_key=label, label=label,
                title=label, url='https://example.com/problem', accepted=True)
        ContestProblemProgress.objects.create(participation=contest, problem_key='C', label='C',
            title='C', url='https://example.com/problem', accepted=False)
        item = Submission.objects.create(team=self.team, member=self.author_member, semester=self.semester,
            week=self.week, problem=self.problem)
        SubmissionPart.objects.create(submission=item, kind='proof', status='approved', points_awarded=1)
        self.assertEqual(self.rows('solved')[0]['value'], 3)
        item.is_valid = False; item.save()
        self.assertEqual(self.rows('solved')[0]['value'], 2)
        item.is_valid = True; item.save()
        cleanup_semester(self.semester)
        self.assertFalse(Submission.objects.filter(pk=item.pk).exists())
        self.assertEqual(self.rows('solved')[0]['value'], 3)
        contest.delete()
        PlatformBinding.objects.filter(user=self.author).delete()
        self.semester.delete()
        self.assertEqual(self.rows('solved')[0]['value'], 3)
        self.assertEqual(SolvedProblemCredit.objects.filter(user=self.author).count(), 3)

    def test_solved_direct_semester_delete_preserves_distinct_problems(self):
        from .models import SubmissionPart
        for _ in range(2):
            item = Submission.objects.create(team=self.team, member=self.author_member, semester=self.semester,
                week=self.week, problem=self.problem)
            SubmissionPart.objects.create(submission=item, kind='proof', status='approved', points_awarded=1)
        self.assertEqual(self.rows('solved')[0]['value'], 1)
        self.semester.delete()
        self.assertEqual(self.rows('solved')[0]['value'], 1)
