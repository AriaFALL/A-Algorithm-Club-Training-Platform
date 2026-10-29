"""Create an isolated ordinary-member account with claimable QA fixtures."""
import secrets
from datetime import date, timedelta
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone
from club.models import (Team, TeamMembership, UserProfile, PlatformBinding,
    ContestParticipation, ContestProblemProgress)
from club.contest_rewards import REWARD_START
from club.currency_services import initialize_default_currency_config
from club.services import build_weeks
from club.models import Semester


class Command(BaseCommand):
    help = 'Create a new isolated RBC demo member; existing users are never overwritten.'

    def add_arguments(self, parser):
        parser.add_argument('--username', default='rbc_demo')

    @transaction.atomic
    def handle(self, *args, **options):
        username = options['username']
        if User.objects.filter(username=username).exists() or Team.objects.filter(code='RBC-REWARD-DEMO').exists():
            raise CommandError('演示账号或团队已存在，未覆盖其数据')
        admin = User.objects.filter(is_superuser=True).first()
        if not admin:
            raise CommandError('请先创建系统管理员')
        password = 'Rbc-' + secrets.token_urlsafe(10)
        user = User.objects.create_user(username=username, password=password)
        team = Team.objects.create(name='RBC 奖励演示（测试）', code='RBC-REWARD-DEMO', created_by=admin,
                                   currency_enabled=True, problem_rewards={'beginner':[1,2,3],'experienced':[1,2,3]})
        member = TeamMembership.objects.create(user=user, team=team, display_name='奖励测试成员', role='member')
        UserProfile.objects.create(user=user, grade=0, grade_date=date(2026,10,29))
        semester = Semester.objects.create(team=team, name='测试学期', starts_on=timezone.localdate()-timedelta(days=7),
                                           ends_on=timezone.localdate()+timedelta(days=120))
        build_weeks(semester)
        initialize_default_currency_config(team)
        cases = [
            ('leetcode','cn:rbc_demo_lc','演示周赛 · 力扣','https://leetcode.cn/contest/',[500,800,1600]),
            ('codeforces','rbc_demo_cf','演示 Round · Codeforces','https://codeforces.com/contests',[800,1200,1800]),
            ('atcoder','rbc_demo_at','演示 ABC · AtCoder','https://atcoder.jp/contests/',[200,600,1200]),
        ]
        for index, (platform,account,title,url,difficulties) in enumerate(cases):
            PlatformBinding.objects.create(user=user,platform=platform,account=account,status='ready',
                snapshot={'display_name':'本地演示数据','notes':['仅用于奖励交互测试，不代表真实平台账号']})
            start = REWARD_START+timedelta(days=index,hours=10)
            contest = ContestParticipation.objects.create(user=user,platform=platform,account=account,
                contest_key='demo-'+platform,title=title,url=url,starts_at=start,ends_at=start+timedelta(hours=2),
                detail_complete=True,source_data={'demo':True,'demo_team_id':team.pk})
            for i in range(5):
                ContestProblemProgress.objects.create(participation=contest,problem_key='demo-'+str(i),
                    label='Q'+str(i+1) if platform=='leetcode' else chr(65+i),title='演示题目 '+str(i+1),url=url,
                    difficulty=difficulties[i] if i<3 else None,difficulty_source='演示难度',accepted=i<3,official_ac=i<3,
                    accepted_at=start+timedelta(minutes=10*(i+1)) if i<2 else None)
        self.stdout.write(f'Account: {username}\nPassword: {password}\nRole: member\nTeam: {team.name}\nUnclaimed: 9 problems / 18 RBC Coins')
