import json
from unittest.mock import patch
from django.test import TestCase, Client
from django.contrib.auth.models import User
from . import test_community as fixtures
from .models import ParserSettings, Problem
from .problem_parser import ai_title, key_cipher, resolve, get_problem


class NavigationUpdatesTests(TestCase):
    setUp = fixtures.CommunityTests.setUp
    image = fixtures.CommunityTests.image
    submit = fixtures.CommunityTests.submit

    def config(self):
        return ParserSettings.objects.update_or_create(pk=1, defaults={'base_url':'https://api.example.com/v1', 'model':'test-model',
            'enabled':True, 'encrypted_key':key_cipher().encrypt(b'test-secret').decode()})[0]

    def test_connection_success_is_distinct_from_unconfirmed_title(self):
        config = self.config()
        raw = json.dumps({'choices':[{'message':{'content':'{"title":null}'}}]})
        with patch('club.problem_parser.http_fetch', return_value=raw):
            self.assertIsNone(ai_title(fixtures.URL, config, allow_unresolved=True))
            with self.assertRaisesRegex(ValueError, 'AI已连接'):
                ai_title(fixtures.URL, config)
            self.client.force_login(User.objects.get(username='admin'))
            data = self.client.post('/api/management/parser/test').json()
            self.assertTrue(data['ok'])
            self.assertIsNone(data['title'])
            self.assertIn('联网', data['warning'])
        with patch('club.problem_parser.http_fetch', side_effect=ValueError('HTTP 401')):
            with self.assertRaisesRegex(ValueError, 'Key 无效'):
                ai_title(fixtures.URL, config)

    def test_remove_task_preserves_submissions_and_blocks_late_results(self):
        item = self.submit()
        self.problem.status = 'running'
        self.problem.generation = 3
        self.problem.save()
        self.assertEqual(self.client.delete(f'/api/management/problems/{self.problem.id}').status_code,403)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.delete(f'/api/management/problems/{self.problem.id}').status_code,200)
        self.problem.refresh_from_db()
        self.assertEqual(self.problem.status,'cancelled')
        self.assertEqual(self.problem.generation,4)
        item.refresh_from_db()
        self.assertTrue(item.is_valid)
        with patch('club.problem_parser.auto_title') as auto:
            resolve(self.problem.id,3,'auto')
            auto.assert_not_called()
        self.assertNotIn(self.problem.id, [p['id'] for p in self.client.get('/api/management/problems').json()['problems']])
        foreign = Problem.objects.create(identity='foreign',url='https://example.com/foreign')
        self.assertEqual(self.client.delete(f'/api/management/problems/{foreign.id}').status_code,404)

    def test_responses_protocol_enables_web_search_and_keeps_url(self):
        config = self.config()
        config.api_protocol = 'responses'
        config.save()
        raw = json.dumps({'output':[{'type':'web_search_call'}, {'type':'message', 'content':[{'type':'output_text','text':'{"title":"水晶铭刻之旅"}'}]}]})
        with patch('club.problem_parser.http_fetch', return_value=raw) as fetch:
            self.assertEqual(ai_title(fixtures.URL,config),'水晶铭刻之旅')
            self.assertEqual(fetch.call_args.args[0], 'https://api.example.com/v1/responses')
            payload = json.loads(fetch.call_args.kwargs['payload'])
            self.assertEqual(payload['input'], fixtures.URL)
            self.assertEqual(payload['tools'], [{'type':'web_search'}])
            self.assertEqual(payload['model'],'test-model')
