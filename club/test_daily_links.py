import io
import json
from unittest.mock import patch, Mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from .daily_views import fetch_leetcode


class DailyLinkTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client.force_login(User.objects.create_user('daily-link-user'))

    def test_current_date_cached_and_method_guard(self):
        url = 'https://leetcode.cn/problems/two-sum/'
        with patch('club.daily_views.fetch_leetcode', return_value=url) as fetch:
            for _ in range(2):
                self.assertEqual(self.client.get('/api/daily-challenges').json()['leetcode']['url'], url)
            fetch.assert_called_once_with(timezone.localdate().isoformat())
        self.assertEqual(self.client.post('/api/daily-challenges').status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.get('/api/daily-challenges').status_code, 401)

    def test_failures_are_temporary_and_never_fake_a_link(self):
        with patch('club.daily_views.fetch_leetcode', side_effect=TimeoutError) as fetch:
            for _ in range(2):
                data = self.client.get('/api/daily-challenges').json()
                self.assertIsNone(data['leetcode']['url'])
            fetch.assert_called_once()

    def test_protocol_and_wrong_date_or_invalid_slug(self):
        today = timezone.localdate().isoformat()
        for date, slug, valid in [(today, 'two-sum', True), ('2000-01-01', 'two-sum', False),
                                  (today, '../../bad', False)]:
            raw = json.dumps({'data': {'todayRecord': [{'date': date, 'question': {'titleSlug': slug}}]}}).encode()
            response = io.BytesIO(raw)
            opener = Mock()
            opener.open.return_value = response
            with patch('club.daily_views.build_opener', return_value=opener):
                if valid:
                    self.assertEqual(fetch_leetcode(today), 'https://leetcode.cn/problems/two-sum/')
                else:
                    with self.assertRaises(ValueError):
                        fetch_leetcode(today)
                req = opener.open.call_args.args[0]
                self.assertTrue(req.full_url.startswith('https://leetcode.cn/graphql/?'))
                self.assertNotIn('Cookie', req.headers)
