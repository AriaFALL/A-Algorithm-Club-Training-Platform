import json
from pathlib import Path
import tempfile
import uuid
import zipfile
from unittest.mock import patch

from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client, TestCase, TransactionTestCase, override_settings
from .models import Team, TeamMembership, CurrencyBalance, CurrencyTransaction
from . import system_backups as backups
from .system_guard import database_guard, epoch


class SystemManagementApiTests(TransactionTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        override = override_settings(SYSTEM_BACKUP_ROOT=Path(self.temp.name))
        override.enable(); self.addCleanup(override.disable)
        self.admin, _ = User.objects.get_or_create(username='admin', defaults={'is_superuser':True,'is_staff':True})
        self.admin.set_password('Admin-old-9462'); self.admin.save()
        self.member = User.objects.create_user('normal-backup-test', password='Member-old-9462')
        self.client.force_login(self.admin)

    def post(self, path, data):
        return self.client.post(path, json.dumps(data), content_type='application/json')

    def test_password_confirmed_in_database_then_all_sessions_invalid(self):
        other = Client(); other.force_login(self.admin)
        data = {'old_password':'Admin-old-9462','new_password':'Admin-new-7492','confirm_password':'Admin-new-7492'}
        response = self.post('/api/management/password', data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['logout'])
        self.admin.refresh_from_db(); self.assertTrue(self.admin.check_password(data['new_password']))
        self.assertEqual(self.client.get('/api/management').status_code, 401)
        self.assertEqual(other.get('/api/management').status_code, 401)
        self.assertFalse(self.client.login(username='admin', password=data['old_password']))
        self.assertTrue(self.client.login(username='admin', password=data['new_password']))

    def test_invalid_password_keeps_hash_and_session(self):
        old_hash = self.admin.password
        for data in [dict(old_password='wrong',new_password='New-9462-pass',confirm_password='New-9462-pass'),
                     dict(old_password='Admin-old-9462',new_password='New-9462-pass',confirm_password='different')]:
            self.assertEqual(self.post('/api/management/password',data).status_code,400)
        self.admin.refresh_from_db(); self.assertEqual(self.admin.password,old_hash)
        self.assertEqual(self.client.get('/api/management').status_code,200)

    def test_member_and_anonymous_cannot_manage_backups_or_admin_password(self):
        for client, code in [(Client(),401),(self.client,403)]:
            if code == 403: client.force_login(self.member)
            self.assertEqual(client.get('/api/management/backups').status_code,code)
            self.assertEqual(client.post('/api/management/backups').status_code,code)
            self.assertEqual(client.post('/api/management/password').status_code,code)

    @patch('club.system_backups.subprocess.Popen')
    def test_backup_start_returns_token_and_download_is_private(self, process):
        process.return_value.pid = 99999999
        response=self.client.post('/api/management/backups')
        self.assertEqual(response.status_code,202)
        operation=response.json(); process.assert_called_once()
        token=operation['id']
        self.assertEqual(Client().get('/api/management/system-operations/'+token).json()['state'],'failed')
        self.assertEqual(Client().get('/api/management/system-operations/'+str(uuid.uuid4())).status_code,404)
        backup_id=str(uuid.uuid4()); path=backups.archive_path(backup_id);path.write_bytes(b'zip')
        backups.write_json(path.with_suffix('.json'),{'id':backup_id,'created_at':'2026-10-29','label':'备份','size':3})
        self.assertEqual(len(self.client.get('/api/management/backups').json()['backups']),1)
        download=self.client.get('/api/management/backups/'+backup_id)
        self.assertEqual(download.status_code,200);self.assertIn('no-store',download['Cache-Control']);download.close()
        self.assertEqual(Client().get('/api/management/backups/'+backup_id).status_code,401)
        self.assertEqual(self.client.delete('/api/management/backups/'+backup_id).status_code,200)

    @patch('club.system_backups.subprocess.Popen')
    def test_restore_requires_current_password_and_explicit_confirmation(self, process):
        process.return_value.pid = 99999999
        backup_id=str(uuid.uuid4());path=backups.archive_path(backup_id);path.write_bytes(b'zip');path.with_suffix('.json').write_text('{}')
        url='/api/management/backups/'+backup_id+'/restore'
        self.assertEqual(self.post(url,{'password':'Admin-old-9462'}).status_code,400)
        self.assertEqual(self.post(url,{'password':'wrong','confirmation':'恢复全部数据'}).status_code,400)
        self.assertEqual(self.post(url,{'password':'Admin-old-9462','confirmation':'恢复全部数据'}).status_code,202)
        process.assert_called_once()

    def test_existing_profile_endpoint_also_logs_out_admin(self):
        response=self.post('/api/profile/password',{'old_password':'Admin-old-9462','new_password':'Admin-new-7492','confirm_password':'Admin-new-7492'})
        self.assertEqual(response.status_code,200);self.assertTrue(response.json()['logout'])
        self.assertEqual(self.client.get('/api/management').status_code,401)


class SystemSnapshotRoundTripTests(TransactionTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        override=override_settings(SYSTEM_BACKUP_ROOT=Path(self.temp.name)/'backups',MEDIA_ROOT=Path(self.temp.name)/'media')
        override.enable();self.addCleanup(override.disable)
        self.admin,_=User.objects.get_or_create(username='admin',defaults={'is_superuser':True,'is_staff':True})
        self.admin.set_password('Backup-root-6917');self.admin.save()
        self.team=Team.objects.create(name='before-backup',code='BACKUP',created_by=self.admin)
        self.member_user=User.objects.create_user('backup-member')
        self.member=TeamMembership.objects.create(user=self.member_user,team=self.team,display_name='测试成员')
        self.balance=CurrencyBalance.objects.create(team=self.team,member=self.member,balance=7)
        CurrencyTransaction.objects.create(team=self.team,member=self.member,amount=7,balance_after=7,transaction_type='admin_adjust')
        from django.conf import settings
        self.media=Path(settings.MEDIA_ROOT);(self.media/'nested').mkdir(parents=True)
        (self.media/'nested'/'test.bin').write_bytes(b'original-file')

    def operation(self,backup_id):
        operation_id=str(uuid.uuid4())
        backups.write_json(backups.status_path(operation_id),{'id':operation_id,'kind':'restore','backup_id':backup_id,'state':'queued','message':''})
        return operation_id

    def test_complete_database_and_media_round_trip_with_safety_backup_and_logout(self):
        client=Client();client.force_login(self.admin)
        with database_guard(exclusive=True): snapshot=backups.create_snapshot()
        Team.objects.filter(pk=self.team.pk).update(name='after-backup')
        CurrencyBalance.objects.filter(pk=self.balance.pk).update(balance=99)
        (self.media/'nested'/'test.bin').write_bytes(b'changed')
        (self.media/'later.txt').write_text('later')
        operation=self.operation(snapshot['id']);backups.run_operation(operation)
        result=backups.read_status(operation);self.assertEqual(result['state'],'completed',result)
        self.team.refresh_from_db();self.balance.refresh_from_db()
        self.assertEqual(self.team.name,'before-backup');self.assertEqual(self.balance.balance,7)
        self.assertEqual((self.media/'nested'/'test.bin').read_bytes(),b'original-file')
        self.assertFalse((self.media/'later.txt').exists());self.assertEqual(Session.objects.count(),0)
        self.assertNotEqual(epoch(),'initial');self.assertTrue(backups.archive_path(result['safety_backup_id']).exists())
        self.assertEqual(client.get('/api/management').status_code,401)
        # Sequence reset must not collide with restored rows.
        self.assertGreater(Team.objects.create(name='new-team',code='NEW-BACKUP',created_by=self.admin).pk,self.team.pk)

    def test_corrupt_or_different_key_backup_cannot_change_database(self):
        snapshot=backups.create_snapshot();path=backups.archive_path(snapshot['id'])
        with override_settings(SECRET_KEY='different-backup-key'):
            with self.assertRaisesRegex(ValueError,'密钥'):
                with backups.checked_archive(path): pass
        with zipfile.ZipFile(path,'a') as archive: archive.writestr('media/../../escape',b'x')
        operation=self.operation(snapshot['id']);backups.run_operation(operation)
        self.assertEqual(backups.read_status(operation)['state'],'failed')
        self.assertTrue(Team.objects.filter(pk=self.team.pk,name='before-backup').exists())
        self.assertEqual((self.media/'nested'/'test.bin').read_bytes(),b'original-file')

    def test_media_failure_rolls_back_database_and_files(self):
        snapshot=backups.create_snapshot()
        Team.objects.filter(pk=self.team.pk).update(name='must-survive')
        (self.media/'nested'/'test.bin').write_bytes(b'must-survive')
        operation=self.operation(snapshot['id'])
        with patch('club.system_backups.shutil.copytree',side_effect=OSError('disk failure')):
            backups.run_operation(operation)
        self.assertEqual(backups.read_status(operation)['state'],'failed')
        self.team.refresh_from_db();self.assertEqual(self.team.name,'must-survive')
        self.assertEqual((self.media/'nested'/'test.bin').read_bytes(),b'must-survive')
        self.assertTrue(backups.archive_path(backups.read_status(operation)['safety_backup_id']).exists())

    def test_tampered_file_hash_is_rejected_before_restore(self):
        snapshot=backups.create_snapshot();path=backups.archive_path(snapshot['id'])
        original=path.read_bytes()
        with zipfile.ZipFile(path) as archive: entries={name:archive.read(name) for name in archive.namelist()}
        entries['media/nested/test.bin']=b'x'*len(entries['media/nested/test.bin'])
        with zipfile.ZipFile(path,'w') as archive:
            for name,data in entries.items():archive.writestr(name,data)
        with self.assertRaisesRegex(ValueError,'内容校验'):
            with backups.checked_archive(path):pass

    def test_schema_mismatch_is_rejected(self):
        snapshot=backups.create_snapshot()
        with patch('club.system_backups.schema',return_value=[]):
            with self.assertRaisesRegex(ValueError,'结构不一致'):
                with backups.checked_archive(backups.archive_path(snapshot['id'])):pass

    def test_restore_lock_blocks_other_requests_and_stale_tasks_are_ignored(self):
        from concurrent.futures import ThreadPoolExecutor
        from django.db import close_old_connections
        def fetch():
            try:return Client().get('/api/me').status_code
            finally:close_old_connections()
        with database_guard(exclusive=True):
            with ThreadPoolExecutor(max_workers=1) as pool:
                self.assertEqual(pool.submit(fetch).result(timeout=5),503)
        self.assertEqual(Client().get('/api/me').status_code,401)
        from .system_task import SystemGuardedTask
        from celery.exceptions import Ignore
        class Probe(SystemGuardedTask):
            def run(self):raise AssertionError('stale task executed')
        from config.celery import app
        Probe.bind(app)
        probe=Probe()
        probe.push_request(headers={'system_epoch':'old-state'},called_directly=False)
        try:
            with self.assertRaises(Ignore):probe()
        finally:probe.pop_request()

    def test_imported_valid_archive_is_listed_only_after_verification(self):
        snapshot=backups.create_snapshot();new_id=str(uuid.uuid4())
        backups.archive_path(new_id).write_bytes(backups.archive_path(snapshot['id']).read_bytes())
        operation=str(uuid.uuid4())
        backups.write_json(backups.status_path(operation),{'id':operation,'kind':'import','backup_id':new_id,'state':'queued','message':''})
        backups.run_operation(operation)
        self.assertEqual(backups.read_status(operation)['state'],'completed')
        self.assertTrue(backups.archive_path(new_id).with_suffix('.json').exists())
