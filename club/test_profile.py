import io
import json
import tempfile
import uuid
from datetime import timedelta
from unittest.mock import patch, Mock

from PIL import Image
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, SimpleTestCase, Client, override_settings
from django.utils import timezone

from .models import Team, TeamMembership, UserProfile, PlatformBinding, FileDeletion
from .tasks import sync_platform_binding
from .platform_sync import codeforces, atcoder, leetcode, luogu, nowcoder, validate_account, SyncError


class ProfileTests(TestCase):
    def setUp(self):
        self.root = User.objects.get(username='admin')
        self.team = Team.objects.create(name='Profile QA', code='PROFILEQA', created_by=self.root)
        self.user = User.objects.create_user('profile-member')
        self.other = User.objects.create_user('profile-other')
        self.member = TeamMembership.objects.create(user=self.user, team=self.team, display_name='Old name')
        TeamMembership.objects.create(user=self.other, team=self.team, display_name='Taken name')
        self.client.force_login(self.user)

    def put(self, platform, account):
        return self.client.put('/api/profile/platforms/' + platform, json.dumps({'account': account}), content_type='application/json')

    def test_member_avatar_is_team_scoped(self):
        url = f'/api/members/{self.member.pk}/avatar'
        self.assertEqual(Client().get(url).status_code, 401)
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            image = io.BytesIO()
            Image.new('RGB', (16, 16), 'red').save(image, format='PNG')
            self.assertEqual(self.client.post('/api/profile', {
                'name': 'Old name', 'avatar': SimpleUploadedFile('avatar.png', image.getvalue(), content_type='image/png')
            }).status_code, 200)
            self.client.force_login(self.other)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Content-Type'], 'image/jpeg')
            self.assertTrue(b''.join(response.streaming_content))
            other_team = Team.objects.create(name='Private', code='AVATARPRIVATE', created_by=self.root)
            outsider = User.objects.create_user('avatar-outsider')
            TeamMembership.objects.create(user=outsider, team=other_team, display_name='Outsider')
            self.client.force_login(outsider)
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_global_luogu_cookie_encrypted_and_admin_only(self):
        from .models import ParserSettings
        from .problem_parser import key_cipher
        url='/api/management/platform-query'
        self.assertEqual(self.client.get(url).status_code,403)
        self.client.force_login(self.root)
        response=self.client.put(url,json.dumps({'cookie':'_uid=7; __client_id=secret-value'}),content_type='application/json')
        self.assertEqual(response.status_code,200)
        config=ParserSettings.objects.get(pk=1)
        self.assertNotIn('secret-value',config.encrypted_luogu_cookie)
        self.assertIn('secret-value',key_cipher().decrypt(config.encrypted_luogu_cookie.encode()).decode())
        self.assertEqual(self.client.get(url).json(),{'has_luogu_cookie':True})
        self.client.put(url,json.dumps({'cookie':''}),content_type='application/json')
        self.assertEqual(self.client.get(url).json(),{'has_luogu_cookie':False})

    def test_profile_access_roles_and_csrf(self):
        self.assertEqual(Client().get('/api/profile').status_code, 401)
        self.assertEqual(self.client.get('/api/profile').status_code, 200)
        self.member.role = 'admin'; self.member.save()
        self.assertEqual(self.client.get('/api/profile').status_code, 200)
        self.client.force_login(self.root)
        self.assertEqual(self.client.get('/api/profile').status_code, 403)
        csrf = Client(enforce_csrf_checks=True); csrf.force_login(self.user)
        self.assertEqual(csrf.post('/api/profile', {'name':'Attempt'}).status_code, 403)
        self.assertEqual(csrf.put('/api/profile/platforms/codeforces', '{}', content_type='application/json').status_code, 403)

    def test_nickname_persists_and_is_team_scoped(self):
        other_team = Team.objects.create(name='Second', code='SECONDPROFILE', created_by=self.root)
        second = TeamMembership.objects.create(user=self.user, team=other_team, display_name='Second name')
        session = self.client.session; session['team_id'] = self.team.pk; session.save()
        self.assertEqual(self.client.post('/api/profile', {'name':'New nickname'}).status_code, 200)
        self.assertEqual(self.client.get('/api/me').json()['name'], 'New nickname')
        second.refresh_from_db(); self.assertEqual(second.display_name, 'Second name')
        self.user.refresh_from_db(); self.assertEqual(self.user.username, 'profile-member')
        self.assertEqual(self.client.post('/api/profile', {'name':'Taken name'}).status_code, 409)
        self.assertEqual(self.client.post('/api/profile', {'name':' '}).status_code, 400)
        self.assertEqual(self.client.post('/api/profile', {'name':'a'*41}).status_code, 400)

    def test_avatar_validation_storage_and_private_delivery(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            def image():
                output=io.BytesIO(); Image.new('RGB',(40,20),'green').save(output,format='PNG')
                return SimpleUploadedFile('photo.png',output.getvalue(),content_type='image/png')
            response = self.client.post('/api/profile', {'name':'Avatar', 'avatar':image()})
            self.assertEqual(response.status_code, 200)
            url = response.json()['avatar']
            response = self.client.get(url)
            content = b''.join(response.streaming_content)
            with Image.open(io.BytesIO(content)) as decoded:
                self.assertEqual(decoded.size, (256,256)); self.assertEqual(decoded.format, 'JPEG')
            old = UserProfile.objects.get(user=self.user).avatar.name
            self.assertEqual(self.client.post('/api/profile', {'avatar':image()}).status_code, 200)
            self.assertTrue(FileDeletion.objects.filter(name=old).exists())
            other_client=Client(); other_client.force_login(self.other)
            self.assertEqual(other_client.get(url).status_code, 404)
            fake=SimpleUploadedFile('bad.png',b'<script>alert(1)</script>',content_type='image/png')
            self.assertEqual(self.client.post('/api/profile', {'name':'Bad','avatar':fake}).status_code,400)
            self.assertEqual(self.client.get('/api/me').json()['name'],'Avatar')

    @patch('club.tasks.sync_platform_binding.delay')
    def test_binding_private_persistent_and_unbind(self, delay):
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.put('codeforces','tourist').status_code,202)
        delay.assert_called_once()
        binding=PlatformBinding.objects.get(user=self.user)
        self.assertEqual(self.client.get('/api/profile').json()['bindings'][0]['account'],'tourist')
        self.assertEqual(self.client.post('/api/profile/platforms/codeforces').status_code,429)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get('/api/profile').json()['bindings'],[])
        self.client.delete('/api/profile/platforms/codeforces')
        self.assertTrue(PlatformBinding.objects.filter(pk=binding.pk).exists())
        self.client.force_login(self.user)
        self.assertEqual(self.client.delete('/api/profile/platforms/codeforces').status_code,200)
        self.assertFalse(PlatformBinding.objects.filter(pk=binding.pk).exists())
        for platform,account in [('qoj','test'),('hdu','test'),('codeforces','https://evil.invalid'),('nowcoder','name')]:
            self.assertEqual(self.put(platform,account).status_code,400)

    @patch('club.platform_sync.fetch_snapshot')
    def test_worker_stale_results_failures_and_success(self, fetch):
        binding=PlatformBinding.objects.create(user=self.user,platform='codeforces',account='tourist',snapshot={'rating':100})
        old_token=str(binding.sync_token)
        fetch.return_value={'rating':200}
        sync_platform_binding(binding.pk,old_token)
        binding.refresh_from_db(); self.assertEqual(binding.snapshot['rating'],200)
        self.assertEqual(binding.status,'ready')
        binding.status='pending'; binding.sync_token=uuid.uuid4(); binding.save()
        fetch.side_effect=SyncError('平台暂不可用')
        sync_platform_binding(binding.pk,str(binding.sync_token))
        binding.refresh_from_db(); self.assertEqual(binding.snapshot['rating'],200); self.assertEqual(binding.status,'failed')
        fetch.reset_mock(); sync_platform_binding(binding.pk,old_token); fetch.assert_not_called()
        binding.status='pending'; binding.requested_at=timezone.now()-timedelta(minutes=5); binding.save()
        row=self.client.get('/api/profile').json()['bindings'][0]
        self.assertEqual(row['status'],'failed'); self.assertIn('超时',row['error'])


class PlatformAdapterTests(SimpleTestCase):
    @patch('club.platform_sync.time.sleep')
    def test_codeforces_deduplicates_and_does_not_call_recent_total(self, sleep):
        remote=Mock()
        remote.json.side_effect=[{'status':'OK','result':[{'handle':'x','rating':1500}]},
            {'status':'OK','result':[{'newRating':1500,'contestName':'C','ratingUpdateTimeSeconds':1}]},
            {'status':'OK','result':[{'verdict':'OK','problem':{'contestId':1,'index':'A','name':'A'}}]*1000}]
        result=codeforces(remote,'x')
        self.assertEqual(result['solved'],1); self.assertIn('1000',result['solved_label'])
        self.assertEqual(result['rating'],1500)

    def test_atcoder_and_optional_failure(self):
        remote=Mock(); remote.json.side_effect=[[{'IsRated':True,'NewRating':1800,'ContestName':'ABC','EndTime':'2026'}], SyncError('offline')]
        remote.text.return_value='<a href="/users/x/history">history</a>'
        result=atcoder(remote,'x')
        self.assertEqual(result['rating'],1800); self.assertNotIn('solved',result); self.assertTrue(result['notes'])

    def test_leetcode_global_and_cn(self):
        for account,initial in [('x',{'matchedUser':{'submitStatsGlobal':{'acSubmissionNum':[{'difficulty':'All','count':10},{'difficulty':'Easy','count':10}]}}}),
                                ('cn:x',{'userProfilePublicProfile':{'username':'x'},'userProfileUserQuestionProgress':{'numAcceptedQuestions':[{'difficulty':'EASY','count':5},{'difficulty':'MEDIUM','count':2}]}})]:
            remote=Mock();remote.json.side_effect=[{'data':initial},{'data':{'userContestRankingHistory':[]}}]
            result=leetcode(remote,account)
            self.assertEqual(result['solved'],7 if account.startswith('cn:') else 10)
            self.assertIsNone(result['rating'])

    def test_nonexistent_cn_account_is_not_reported_as_zero_solved(self):
        remote = Mock()
        remote.json.return_value = {'data': {'userProfilePublicProfile': None,
            'userProfileUserQuestionProgress': {'numAcceptedQuestions': []}}}
        with self.assertRaises(SyncError):
            leetcode(remote, 'cn:nonexistent')

    def test_luogu_and_nowcoder(self):
        remote=Mock();remote.text.side_effect=[json.dumps({'data':{'user':{'uid':12,'name':'Name'},'elo':[]}}),json.dumps({'data':{'passed':[{'pid':'P1'}]}})]
        self.assertEqual(luogu(remote,'12')['solved'],1)
        remote=Mock();remote.text.return_value='<script>window.curUser.id = "123";</script><table><tr><td><a href="/acm/problem/1001">题</a></td></tr></table>'
        remote.json.return_value={'code':0,'data':[{'contestId':1,'rating':'1500','time':100}]}
        result=nowcoder(remote,'123');self.assertEqual(result['rating'],1500);self.assertEqual(result['solved'],1)
        remote.text.return_value='<html>验证码</html>'
        with self.assertRaises(SyncError): nowcoder(remote,'123')
