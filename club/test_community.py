import importlib
import io
import json
import tempfile
from datetime import timedelta
from unittest.mock import patch, Mock

from PIL import Image
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, TransactionTestCase, Client, override_settings
from django.utils import timezone

from .models import (Problem, ParserSettings, Submission, SubmissionLike, SubmissionReport,
                     SubmissionPart, Semester, Team, TeamMembership, FileDeletion, SemesterMemberTotal)
from .problem_parser import canonical_problem, resolve, enqueue_problem, get_problem, ai_title, auto_title, key_cipher, http_fetch
from .services import build_weeks, refresh_totals, settle_week
from .tasks import purge_files

URL = 'https://www.nowcoder.com/practice/d53b2057ae8a4eaf8155447f6b709361'


class CommunityTests(TestCase):
    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        context = override_settings(MEDIA_ROOT=self.media.name, USE_X_ACCEL_REDIRECT=False)
        context.enable()
        self.addCleanup(context.disable)
        self.owner = User.objects.create_user('owner', password='test-password')
        self.author = User.objects.create_user('author', password='test-password')
        self.reader = User.objects.create_user('reader', password='test-password')
        self.team = Team.objects.create(name='Team', code='T', created_by=self.owner)
        self.owner_member = TeamMembership.objects.create(team=self.team, user=self.owner, display_name='管理员', role='admin')
        self.author_member = TeamMembership.objects.create(team=self.team, user=self.author, display_name='A同学')
        TeamMembership.objects.create(team=self.team, user=self.reader, display_name='B同学')
        today = timezone.localdate()
        self.semester = Semester.objects.create(team=self.team, name='当前学期', starts_on=today-timedelta(days=14), ends_on=today+timedelta(days=30))
        build_weeks(self.semester)
        self.week = self.semester.weeks.get(starts_at__lte=timezone.now(), ends_at__gt=timezone.now())
        self.problem = Problem.objects.create(identity='nowcoder:test', url=URL)
        self.client.force_login(self.author)

    def image(self):
        data = io.BytesIO()
        Image.new('RGB', (3, 3), 'white').save(data, 'PNG')
        return SimpleUploadedFile('proof.png', data.getvalue(), content_type='image/png')

    def post(self, path, data):
        return self.client.post(path, json.dumps(data), content_type='application/json')

    def submit(self):
        with patch('club.problem_parser.get_problem', return_value=self.problem):
            response = self.client.post('/api/submissions', {'problem_url': URL, 'week_id': self.week.pk,
                'proof': self.image(), 'logic': '完整题解\n第二行', 'blog': 'https://example.com/blog'})
        self.assertEqual(response.status_code, 201, response.content)
        return Submission.objects.get(pk=response.json()['submission']['id'])

    def report(self, submission):
        self.client.force_login(self.reader)
        return self.post(f'/api/submissions/{submission.pk}/report', {})

    def reject(self, submission):
        self.client.force_login(self.owner)
        return self.post(f'/api/admin/reports/{submission.pk}/resolve', {'action':'reject', 'version':submission.version, 'note':'截图不匹配'})

    def test_immediate_scores_and_grouped_history(self):
        current = self.submit()
        total = SemesterMemberTotal.objects.get(member=self.author_member)
        self.assertEqual((total.total_score, total.total_submissions), (3, 1))
        self.assertEqual(current.parts.filter(status='approved').count(), 3)
        prior = self.semester.weeks.filter(number__lt=self.week.number).first()
        older = Submission.objects.create(team=self.team, member=self.author_member, semester=self.semester, week=prior, problem=self.problem)
        SubmissionPart.objects.create(submission=older, kind='logic', status='approved', text_content='历史题解')
        other_term = Semester.objects.create(team=self.team, name='旧学期', starts_on=timezone.localdate()-timedelta(days=60), ends_on=timezone.localdate()-timedelta(days=31), is_active=False)
        build_weeks(other_term)
        Submission.objects.create(team=self.team, member=self.author_member, semester=other_term, week=other_term.weeks.first(), problem=self.problem)
        gallery = self.client.get('/api/showcase').json()
        self.assertEqual(gallery['problems'][0]['count'], 1)
        self.assertEqual(gallery['problems'][0]['title'], URL)
        detail = self.client.get(f'/api/problems/{self.problem.pk}/submissions').json()
        self.assertEqual(len(detail['submissions']), 3)
        previous = self.client.get(f'/api/showcase?week={prior.pk}').json()
        self.assertEqual(previous['problems'][0]['count'], 1)

    def test_showcase_only_lists_started_weeks_and_opens_at_boundary(self):
        future = self.semester.weeks.filter(starts_at__gt=timezone.now()).order_by('starts_at').first()
        with patch('django.utils.timezone.now', return_value=future.starts_at-timedelta(seconds=1)):
            data = self.client.get('/api/showcase').json()
            expected = list(self.semester.weeks.filter(starts_at__lt=future.starts_at)
                            .order_by('-starts_at').values_list('pk', flat=True))
            self.assertEqual([w['id'] for w in data['weeks']], expected)
            self.assertEqual(data['week'], expected[0])
            self.assertEqual(self.client.get(f'/api/showcase?week={future.pk}').status_code, 404)
        with patch('django.utils.timezone.now', return_value=future.starts_at):
            data = self.client.get('/api/showcase').json()
            self.assertEqual(data['weeks'][0]['id'], future.pk)
            self.assertEqual(data['week'], future.pk)
            self.assertEqual(data['current_week'], future.pk)

    def test_showcase_defaults_to_latest_history_when_no_current_week(self):
        with patch('django.utils.timezone.now', return_value=self.semester.weeks.latest('ends_at').ends_at+timedelta(days=1)):
            self.client.force_login(self.author)
            data = self.client.get('/api/showcase').json()
        self.assertIsNone(data['current_week'])
        self.assertEqual(data['week'], self.semester.weeks.latest('starts_at').pk)

    def test_showcase_empty_before_first_week(self):
        with patch('django.utils.timezone.now', return_value=self.semester.weeks.earliest('starts_at').starts_at-timedelta(seconds=1)):
            data = self.client.get('/api/showcase').json()
        self.assertEqual(data['weeks'], [])
        self.assertIsNone(data['week'])
        self.assertEqual(data['problems'], [])

    def test_problem_history_paginates_by_record_date_before_upload_time(self):
        today = timezone.localdate()
        records = [Submission.objects.create(team=self.team, member=self.author_member,
            semester=self.semester, week=self.week, problem=self.problem, record_date=today)
            for _ in range(21)]
        makeup = Submission.objects.create(team=self.team, member=self.author_member,
            semester=self.semester, week=self.week, problem=self.problem, record_date=today-timedelta(days=1))
        first = self.client.get(f'/api/problems/{self.problem.pk}/submissions').json()
        second = self.client.get(f'/api/problems/{self.problem.pk}/submissions?page=2').json()
        self.assertEqual([s['id'] for s in first['submissions']], [s.pk for s in reversed(records[1:])])
        self.assertEqual(first['next'], 2)
        self.assertEqual([s['id'] for s in second['submissions']], [records[0].pk, makeup.pk])
        self.assertEqual(second['submissions'][-1]['record_date'], (today-timedelta(days=1)).isoformat())
        self.assertIsNone(second['next'])

    def test_same_problem_two_members_and_pagination(self):
        self.submit()
        self.client.force_login(self.reader)
        self.submit()
        gallery = self.client.get('/api/showcase').json()['problems'][0]
        self.assertEqual(gallery['count'], 2)
        self.assertEqual(gallery['members'], ['A同学', 'B同学'])
        for _ in range(22):
            Submission.objects.create(team=self.team, member=self.author_member, semester=self.semester, week=self.week, problem=self.problem)
        data = self.client.get(f'/api/problems/{self.problem.pk}/submissions').json()
        self.assertEqual(len(data['submissions']), 20)
        self.assertEqual(data['next'], 2)

    def test_like_is_idempotent_cancelable_and_self_forbidden(self):
        submission = self.submit()
        path = f'/api/submissions/{submission.pk}/like'
        self.assertEqual(self.client.put(path).status_code, 403)
        self.client.force_login(self.reader)
        for _ in range(2):
            self.assertEqual(self.client.put(path).json()['likes'], 1)
        self.assertEqual(self.client.delete(path).json()['likes'], 0)
        self.assertEqual(self.client.delete(path).json()['likes'], 0)

    def test_report_dismiss_reject_and_resubmit_versions(self):
        submission = self.submit()
        old_proof = submission.parts.get(kind='proof')
        for _ in range(2):
            self.assertEqual(self.report(submission).status_code, 200)
        self.assertEqual(submission.reports.count(), 1)
        self.client.put(f'/api/submissions/{submission.pk}/like')
        # Reports keep material visible until a decision.
        self.assertEqual(self.client.get(f'/api/attachments/{old_proof.pk}').status_code, 200)
        self.assertEqual(self.reject(submission).status_code, 200)
        self.assertEqual(self.reject(submission).status_code, 409)
        total = SemesterMemberTotal.objects.get(member=self.author_member)
        self.assertEqual((total.total_score, total.total_submissions), (0, 0))
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(f'/api/attachments/{old_proof.pk}').status_code, 404)
        self.assertEqual(self.client.get(f'/api/problems/{self.problem.pk}/submissions').status_code, 404)
        self.client.force_login(self.author)
        self.assertEqual(self.client.get(f'/api/attachments/{old_proof.pk}').status_code, 200)
        with patch('club.problem_parser.get_problem', return_value=self.problem):
            response = self.client.post(f'/api/submissions/{submission.pk}/resubmit', {'week_id': self.week.pk, 'problem_url': URL, 'proof': self.image()})
        self.assertEqual(response.status_code, 201, response.content)
        submission.refresh_from_db()
        self.assertEqual(submission.version, 2)
        self.assertEqual(submission.likes.count(), 0)
        self.assertEqual(submission.reports.get().version, 1)
        self.assertTrue(FileDeletion.objects.filter(name=old_proof.upload.name).exists())
        self.assertEqual(self.report(submission).status_code, 200)
        self.assertEqual(submission.reports.count(), 2)

    def test_dismiss_does_not_change_score_and_duplicate_report_stays_dismissed(self):
        submission = self.submit()
        self.report(submission)
        self.client.force_login(self.owner)
        result = self.post(f'/api/admin/reports/{submission.pk}/resolve', {'action':'dismiss', 'version':1})
        self.assertEqual(result.status_code, 200)
        self.report(submission)
        self.assertEqual(submission.reports.get().status, 'dismissed')
        self.assertEqual(SemesterMemberTotal.objects.get(member=self.author_member).total_score, 3)

    def test_cross_team_and_own_report_resolution_denied(self):
        submission = self.submit()
        stranger = User.objects.create_user('stranger')
        team = Team.objects.create(code='OTHER', name='Other', created_by=stranger)
        TeamMembership.objects.create(team=team, user=stranger, display_name='外部', role='admin')
        self.client.force_login(stranger)
        for path in [f'/api/problems/{self.problem.pk}/submissions', f'/api/attachments/{submission.parts.get(kind="proof").pk}']:
            self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.post(f'/api/submissions/{submission.pk}/report', {}).status_code, 404)
        self.report(submission)
        self.author_member.role = 'admin'
        self.author_member.save()
        self.client.force_login(self.author)
        self.assertEqual(self.post(f'/api/admin/reports/{submission.pk}/resolve', {'action':'reject','version':1,'note':'x'}).status_code, 403)

    def test_resubmit_deadline_and_archive(self):
        submission = self.submit()
        self.report(submission)
        self.reject(submission)
        self.client.force_login(self.author)
        with patch('django.utils.timezone.now', return_value=self.week.ends_at):
            result = self.client.post(f'/api/submissions/{submission.pk}/resubmit', {'week_id':self.week.pk, 'problem_url':URL, 'proof':self.image()})
        self.assertEqual(result.status_code, 409)
        submission.refresh_from_db()
        self.assertFalse(submission.is_valid)

    def test_reject_closed_week_recomputes_qualification_and_archive_blocks_actions(self):
        self.semester.min_submissions = self.semester.min_score = 1
        self.semester.save()
        submission = self.submit()
        self.report(submission)
        with patch('django.utils.timezone.now', return_value=self.week.ends_at):
            settle_week(self.week)
            self.assertEqual(SemesterMemberTotal.objects.get(member=self.author_member).qualified_weeks, 1)
            self.assertEqual(self.reject(submission).status_code, 200)
        self.assertEqual(SemesterMemberTotal.objects.get(member=self.author_member).qualified_weeks, 0)
        self.semester.archived_at = timezone.now()
        self.semester.save()
        self.assertEqual(self.report(submission).status_code, 409)
        self.assertEqual(self.reject(submission).status_code, 409)

    def test_old_routes_removed_and_non_admin_queue_denied(self):
        for path in ['/api/arena', '/api/admin/arena', '/api/admin/submissions/bulk-approve']:
            self.assertEqual(self.client.post(path).status_code, 404)
        self.assertEqual(self.client.get('/api/admin/reports').status_code, 403)


class ParserTests(TestCase):
    def test_identity_variants(self):
        self.assertEqual(canonical_problem(URL)[0], canonical_problem(URL+'?channelPut=tracker2')[0])
        pairs = [
            ('https://leetcode.cn/problems/two-sum/description/', 'https://leetcode.com/problems/two-sum'),
            ('https://codeforces.com/problemset/problem/123/A', 'https://codeforces.com/contest/123/problem/A'),
            ('https://www.luogu.com.cn/problem/P1001?utm_source=x', 'https://www.luogu.com.cn/problem/P1001'),
            ('https://atcoder.jp/contests/abc100/tasks/abc100_a?lang=en', 'https://atcoder.jp/contests/abc100/tasks/abc100_a'),
        ]
        for left, right in pairs:
            self.assertEqual(canonical_problem(left)[0], canonical_problem(right)[0])
        self.assertNotEqual(canonical_problem('https://example.com/?id=1')[0], canonical_problem('https://example.com/?id=2')[0])
        for bad in ['http://127.0.0.1/x', 'http://localhost/x', 'http://192.168.1.1/', 'http://[fd00::1]/', 'http://2130706433/', 'javascript:alert(1)']:
            with self.assertRaises(ValidationError):
                canonical_problem(bad)

    def test_ssrf_dns_is_checked_before_connect(self):
        with patch('socket.getaddrinfo', return_value=[(2,1,6,'',('127.0.0.1',80))]), patch('socket.create_connection') as connect:
            with self.assertRaises(ValueError):
                http_fetch('https://public.example/problem')
            connect.assert_not_called()

    def test_mode_dispatch(self):
        for mode, automatic, ai in [('auto',1,0), ('ai',0,1), ('smart',1,0)]:
            problem = Problem.objects.create(identity=mode, url=URL, mode=mode, generation=1)
            with patch('club.problem_parser.auto_title', return_value='水晶铭刻之旅') as a, patch('club.problem_parser.ai_title', return_value='水晶铭刻之旅') as b:
                resolve(problem.pk, 1, mode)
                self.assertEqual((a.call_count,b.call_count), (automatic,ai))
            problem.refresh_from_db()
            self.assertEqual(problem.title, '水晶铭刻之旅')

    def test_smart_fallback_and_failure_keeps_previous_title(self):
        problem = Problem.objects.create(identity='smart', url=URL, generation=1, title='原题名')
        with patch('club.problem_parser.auto_title', side_effect=ValueError()), patch('club.problem_parser.ai_title', side_effect=ValueError('AI未配置')) as ai:
            resolve(problem.pk, 1, 'smart')
            ai.assert_called_once()
        problem.refresh_from_db()
        self.assertEqual((problem.status,problem.title), ('failed','原题名'))
        self.assertIn('AI未配置', problem.error)

    def test_get_problem_and_mode_change_do_not_repeat_requests(self):
        with patch('club.tasks.resolve_problem.apply_async') as dispatch, self.captureOnCommitCallbacks(execute=True):
            a = get_problem(URL)
            b = get_problem(URL+'?channelPut=tracker2')
            settings = ParserSettings.objects.get(pk=1)
            settings.mode='ai'; settings.save()
            get_problem(URL)
        self.assertEqual(a.pk,b.pk)
        dispatch.assert_called_once()
        a.refresh_from_db()
        self.assertEqual(a.mode,'smart')
        with patch('club.tasks.resolve_problem.apply_async') as dispatch, self.captureOnCommitCallbacks(execute=True):
            enqueue_problem(a, 'ai')
        self.assertEqual(dispatch.call_args.kwargs['args'][2], 'ai')

    def test_manual_title_wins_over_late_ai(self):
        problem = Problem.objects.create(identity='late', url=URL, generation=1)
        def manual(url):
            Problem.objects.filter(pk=problem.pk).update(title='人工题名', generation=2, status='manual')
            return '迟到结果'
        with patch('club.problem_parser.ai_title', side_effect=manual):
            resolve(problem.pk, 1, 'ai')
        problem.refresh_from_db()
        self.assertEqual(problem.title,'人工题名')

    def test_ai_wire_format_and_invalid_responses(self):
        config = ParserSettings.objects.get(pk=1)
        config.base_url='https://api.example/v1'
        config.model='test-model'
        config.encrypted_key=key_cipher().encrypt(b'secret-test').decode()
        config.save()
        response = json.dumps({'choices':[{'message':{'content':json.dumps({'title':'水晶铭刻之旅'})}}]})
        with patch('club.problem_parser.http_fetch',return_value=response) as fetch:
            self.assertEqual(ai_title(URL,config),'水晶铭刻之旅')
            args=fetch.call_args
            self.assertEqual(args.args[0],'https://api.example/v1/chat/completions')
            payload=json.loads(args.kwargs['payload'])
            self.assertEqual(payload['messages'][1]['content'],URL)
            self.assertEqual(payload['model'],'test-model')
            self.assertNotIn('secret-test',config.encrypted_key)
        for value in ['invalid', json.dumps({'choices':[{'message':{'content':'{"title":null}'}}]})]:
            with patch('club.problem_parser.http_fetch',return_value=value), self.assertRaises(ValueError):
                ai_title(URL,config)

    def test_auto_platform_titles_and_error_pages(self):
        samples = [('题目 - 牛客网','题目'), ('P1001 A+B Problem - 洛谷','P1001 A+B Problem'),
                   ('两数之和 - 力扣（LeetCode）','两数之和'), ('Problem - 123A - Codeforces','123A'),
                   ('A - Water - AtCoder','A - Water')]
        for page, expected in samples:
            with patch('club.problem_parser.http_fetch',return_value=f'<html><title>{page}</title></html>'):
                self.assertEqual(auto_title(URL),expected)
        for page in ['Just a moment...', '牛客网', '验证码', '404 Not Found']:
            with patch('club.problem_parser.http_fetch',return_value=f'<title>{page}</title>'), self.assertRaises(ValueError):
                auto_title(URL)
        with patch('club.problem_parser.http_fetch', return_value='<title>Problem - 123A - Codeforces</title><div class="title">A. Prime Permutation</div>'):
            self.assertEqual(auto_title('https://codeforces.com/problemset/problem/123/A'), 'A. Prime Permutation')
        with patch('club.problem_parser.http_fetch', return_value='<title>AtCoder</title><span class="h2">A - Water</span>'):
            self.assertEqual(auto_title('https://atcoder.jp/contests/abc100/tasks/abc100_a'), 'A - Water')

    def test_file_cleanup_is_retryable(self):
        FileDeletion.objects.create(name='old.png')
        with patch('club.tasks.default_storage.delete',side_effect=OSError()):
            purge_files()
        self.assertTrue(FileDeletion.objects.exists())
        with patch('club.tasks.default_storage.delete'):
            purge_files()
        self.assertFalse(FileDeletion.objects.exists())


class UpgradeTests(TransactionTestCase):
    def test_destructive_upgrade_preserves_identity_and_manifests_files(self):
        from django.apps import apps
        from django.db.migrations.executor import MigrationExecutor
        migration = importlib.import_module('club.migrations.0008_community_library')
        old_apps = MigrationExecutor(connection).loader.project_state([('club', '0007_archive_state')]).apps
        Arena = old_apps.get_model('club', 'Arena')
        with connection.schema_editor() as editor:
            editor.create_model(Arena)
        try:
            user = User.objects.create_user('upgrade-owner')
            team = Team.objects.create(code='UPGRADE', name='Upgrade', created_by=user)
            member = TeamMembership.objects.create(team=team, user=user, display_name='原成员')
            today = timezone.localdate()
            semester = Semester.objects.create(team=team, name='原学期', starts_on=today, ends_on=today+timedelta(days=10))
            build_weeks(semester)
            submission = Submission.objects.create(team=team, member=member, semester=semester, week=semester.weeks.first())
            SubmissionPart.objects.create(submission=submission, kind='proof', upload='old-proof.png')
            SemesterMemberTotal.objects.create(semester=semester, member=member, total_score=20)
            Arena.objects.create(team_id=team.pk, title='Old', opens_at=timezone.now(), closes_at=timezone.now(), judge_script='old-script.py')
            class MixedApps:
                def get_model(self, label, name):
                    return Arena if name == 'Arena' else apps.get_model(label, name)
            with connection.schema_editor() as editor:
                migration.clear_training_history(MixedApps(), editor)
                editor.deferred_sql.append('CREATE INDEX upgrade_trigger_check ON club_submission (week_id)')
            self.assertFalse(Submission.objects.exists())
            self.assertFalse(SemesterMemberTotal.objects.exists())
            self.assertEqual(set(FileDeletion.objects.values_list('name', flat=True)), {'old-proof.png','old-script.py'})
            self.assertTrue(User.objects.filter(pk=user.pk).exists())
            self.assertTrue(TeamMembership.objects.filter(pk=member.pk).exists())
            self.assertTrue(Semester.objects.filter(pk=semester.pk).exists())
        finally:
            with connection.schema_editor() as editor:
                editor.execute('DROP INDEX IF EXISTS upgrade_trigger_check')
                editor.delete_model(Arena)


class CommunityConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.admin = User.objects.create_user('team-manager')
        self.author = User.objects.create_user('author')
        self.reader = User.objects.create_user('reader')
        self.team = Team.objects.create(code='CONCURRENT', name='Team', created_by=self.admin)
        TeamMembership.objects.create(team=self.team, user=self.admin, display_name='管理员', role='admin')
        self.member = TeamMembership.objects.create(team=self.team, user=self.author, display_name='作者')
        TeamMembership.objects.create(team=self.team, user=self.reader, display_name='读者')
        today = timezone.localdate()
        self.semester = Semester.objects.create(team=self.team, name='学期', starts_on=today-timedelta(days=7), ends_on=today+timedelta(days=7))
        build_weeks(self.semester)
        week = self.semester.weeks.get(starts_at__lte=timezone.now(), ends_at__gt=timezone.now())
        self.submission = Submission.objects.create(team=self.team, member=self.member, semester=self.semester, week=week)
        SubmissionPart.objects.create(submission=self.submission, kind='proof', status='approved', points_awarded=1)
        SubmissionReport.objects.create(submission=self.submission, version=1, reporter=self.reader)

    def concurrent(self, operation):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import connections
        barrier = Barrier(2)
        def run():
            try:
                client = Client()
                client.force_login(self.admin if operation == 'resolve' else self.reader)
                barrier.wait(timeout=10)
                if operation == 'resolve':
                    return client.post(f'/api/admin/reports/{self.submission.pk}/resolve', json.dumps({'action':'reject','note':'不匹配','version':1}), content_type='application/json').status_code
                if operation == 'like':
                    return client.put(f'/api/submissions/{self.submission.pk}/like').status_code
                return client.post(f'/api/submissions/{self.submission.pk}/report').status_code
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run) for _ in range(2)]
            return sorted(f.result(timeout=30) for f in futures)

    def test_concurrent_resolution_reverses_once(self):
        self.assertEqual(self.concurrent('resolve'), [200, 409])
        self.submission.refresh_from_db()
        self.assertFalse(self.submission.is_valid)
        self.assertEqual(self.submission.review_logs.count(), 1)
        self.assertEqual(SemesterMemberTotal.objects.get(member=self.member).total_score, 0)

    def test_concurrent_likes_and_reports_are_unique(self):
        self.assertEqual(self.concurrent('like'), [200,200])
        self.assertEqual(self.submission.likes.count(), 1)
        self.assertEqual(self.concurrent('report'), [200,200])
        self.assertEqual(self.submission.reports.count(), 1)
