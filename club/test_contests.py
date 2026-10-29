import html
import json
import io
from concurrent.futures import ThreadPoolExecutor
from email.message import Message
from http.cookiejar import CookieJar
from unittest.mock import patch, Mock
from urllib.error import HTTPError
from urllib.response import addinfourl

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, SimpleTestCase, TransactionTestCase
from datetime import timedelta
from .models import ContestCalendarSnapshot
from django.db import connections
from django.utils import timezone

from .contest_views import contest, parse_calendar, platform_snapshot, fetch_luogu_calendar, LUOGU_CALENDAR_URL


class LuoguCookieTests(SimpleTestCase):
    def response(self, code=200, cookie=None, location=None, body=b'{}'):
        headers = Message()
        if cookie:
            headers['Set-Cookie'] = cookie
        if location:
            headers['Location'] = location
        if code != 200:
            return HTTPError(LUOGU_CALENDAR_URL, code, 'redirect', headers, io.BytesIO(body))
        return addinfourl(io.BytesIO(body), headers, LUOGU_CALENDAR_URL, code)

    def test_handshake_and_cookie_reuse(self):
        opener = Mock()
        opener.open.side_effect = [
            self.response(302, 'C3VK=anonymous; Max-Age=300; Path=/; Secure', LUOGU_CALENDAR_URL),
            self.response(body=b'{"data":1}'), self.response(),
        ]
        with patch('club.contest_views._luogu_cookies', CookieJar()), patch('club.contest_views.build_opener',return_value=opener), patch('club.contest_views.time.sleep') as sleep:
            self.assertEqual(fetch_luogu_calendar(), '{"data":1}')
            fetch_luogu_calendar()
        requests = [call.args[0] for call in opener.open.call_args_list]
        self.assertIsNone(requests[0].get_header('Cookie'))
        self.assertEqual(requests[1].get_header('Cookie'), 'C3VK=anonymous')
        self.assertEqual(requests[2].get_header('Cookie'), 'C3VK=anonymous')
        self.assertTrue(all(req.full_url == LUOGU_CALENDAR_URL for req in requests))
        sleep.assert_called_once_with(0.3)

    def test_handshake_has_bounded_retries(self):
        opener = Mock()
        opener.open.side_effect = [self.response(302, f'C3VK=anon{i}; Max-Age=300; Path=/', LUOGU_CALENDAR_URL) for i in range(3)]
        with patch('club.contest_views._luogu_cookies', CookieJar()), patch('club.contest_views.build_opener',return_value=opener), patch('club.contest_views.time.sleep') as sleep:
            with self.assertRaisesRegex(ValueError, 'retry limit'):
                fetch_luogu_calendar()
        self.assertEqual(opener.open.call_count,3)
        self.assertEqual(sleep.call_count,2)

    def test_other_redirects_errors_and_unusable_cookies_are_not_retried(self):
        cases = [
            (302, None, LUOGU_CALENDAR_URL),
            (302, 'C3VK=anon; Path=/', 'https://example.com/'),
            (302, 'C3VK=anon; Path=/', None),
            (302, 'C3VK=anon; Domain=example.com; Path=/', LUOGU_CALENDAR_URL),
            (302, 'C3VK=anon; Max-Age=0; Path=/', LUOGU_CALENDAR_URL),
            (403, None, None),
        ]
        for code, cookie, location in cases:
            with self.subTest(code=code,cookie=cookie,location=location):
                opener = Mock()
                opener.open.side_effect = self.response(code,cookie,location)
                with patch('club.contest_views._luogu_cookies', CookieJar()), patch('club.contest_views.build_opener',return_value=opener), patch('club.contest_views.time.sleep') as sleep:
                    with self.assertRaises(HTTPError):
                        fetch_luogu_calendar()
                self.assertEqual(opener.open.call_count,1)
                sleep.assert_not_called()


class CalendarParsingTests(SimpleTestCase):
    def test_atcoder_timezone_duration_entities_and_bad_rows(self):
        raw = '''<div id="contest-table-upcoming"><table>
        <tr><td><time class="fixtime-full">2026-10-31 21:00:00+0900</time></td>
        <td><a href="/contests/abc999">ABC &amp; friends</a></td><td>01:40</td></tr>
        <tr><td><a href="/contests/invalid">Missing time</a></td></tr></table></div>'''
        rows = parse_calendar('atcoder', raw)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['name'], 'ABC & friends')
        self.assertEqual(rows[0]['end']-rows[0]['start'], 6000)
        self.assertEqual(rows[0]['start'], 1793448000)

    def test_nowcoder_double_escaped_json_and_deduplication(self):
        row = {'contestId': 123, 'contestName': '牛客周赛', 'contestStartTime': 1793448000000, 'contestEndTime': 1793455200000}
        raw = '<li data-json="' + html.escape(html.escape(json.dumps(row))) + '"></li>'
        rows = parse_calendar('nowcoder', raw*2)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['url'], 'https://ac.nowcoder.com/acm/contest/123')
        self.assertEqual(rows[0]['end']-rows[0]['start'], 7200)

    def test_cf_luogu_and_untrusted_or_invalid_records(self):
        cf = {'status':'OK','result':[{'id':1,'name':'Round','startTimeSeconds':100,'durationSeconds':7200}, {'id':2}]}
        self.assertEqual(len(parse_calendar('codeforces',json.dumps(cf))),1)
        lg = {'data':{'contests':{'result':[{'id':1,'name':'月赛','startTime':100,'endTime':200}]}}}
        self.assertEqual(parse_calendar('luogu',json.dumps(lg))[0]['end'],200)
        for cid, start, end in [('https://evil.test',100,200), ('abc',float('nan'),200), ('abc',200,100)]:
            with self.assertRaises(ValueError):
                contest('atcoder',cid,'Title',start,end)
        with self.assertRaises(ValueError):
            parse_calendar('atcoder','<html>captcha</html>')

class CalendarRefreshTests(TransactionTestCase):
    def test_persistence_failure_retains_success_and_manual_refresh_is_throttled(self):
        row = contest('codeforces',1,'Round',100,200)
        def fetch_one(platform):
            try: return platform_snapshot(platform)
            finally: connections.close_all()
        with patch('club.contest_views.fetch_platform',return_value=[row]) as fetch:
            with ThreadPoolExecutor(4) as pool:
                results = list(pool.map(fetch_one,['codeforces']*4))
            self.assertEqual(fetch.call_count,1)
        ContestCalendarSnapshot.objects.filter(platform='codeforces').update(attempted_at=timezone.now()-timedelta(hours=1))
        with patch('club.contest_views.fetch_platform',side_effect=TimeoutError) as fetch:
            stale=platform_snapshot('codeforces')
            self.assertTrue(stale['stale'])
            self.assertEqual(stale['contests'],[row])
            self.assertEqual(stale['updated_at'],results[0]['updated_at'])
            platform_snapshot('codeforces')
            self.assertEqual(fetch.call_count,1)

    def test_background_task_forces_update_even_with_recent_manual_cache(self):
        from club.tasks import refresh_contest_calendar
        with patch('club.contest_views.refresh_calendar',return_value={}) as refresh:
            refresh_contest_calendar()
        refresh.assert_called_once_with(force=True)

    def test_schedule_is_twice_daily_in_shanghai(self):
        from django.conf import settings
        schedule=settings.CELERY_BEAT_SCHEDULE['refresh-contest-calendar']['schedule']
        self.assertEqual(schedule.hour,{6,18})
        self.assertEqual(schedule.minute,{0})
        self.assertEqual(settings.CELERY_TIMEZONE,'Asia/Shanghai')


class CalendarApiTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user('calendar-reader'))

    def test_window_sort_partial_failure_and_permissions(self):
        now = timezone.now().timestamp()
        def snapshot(platform):
            return {'contests': [] if platform != 'codeforces' else [
                contest(platform,1,'Later',now+1000,now+2000),
                contest(platform,2,'Soon',now+100,now+200),
                contest(platform,3,'Old',now-900000,now-800000),
                contest(platform,4,'Far',now+100*86400,now+101*86400)],
                'updated_at':None,'stale':False,'error':None if platform=='codeforces' else 'unavailable'}
        for platform in ['codeforces','atcoder','nowcoder','luogu','leetcode']:
            data=snapshot(platform)
            ContestCalendarSnapshot.objects.create(platform=platform,contests=data['contests'],error=data['error'] or '')
        with patch('club.contest_views.fetch_platform') as fetch:
            response = self.client.get('/api/contests')
        fetch.assert_not_called()
        self.assertEqual(response.status_code,200)
        self.assertEqual([c['name'] for c in response.json()['contests']],['Soon','Later'])
        self.assertEqual(len(response.json()['sources']),5)
        self.assertEqual(self.client.post('/api/contests').status_code,405)
        self.client.logout()
        self.assertEqual(self.client.get('/api/contests').status_code,401)

    def test_cold_cache_is_read_only_and_manual_refresh_is_explicit(self):
        with patch('club.contest_views.fetch_platform') as fetch:
            data=self.client.get('/api/contests').json()
        fetch.assert_not_called()
        self.assertEqual(data['contests'],[])
        self.assertTrue(all(s['error'] for s in data['sources']))
        self.assertFalse(ContestCalendarSnapshot.objects.exists())
        snapshots={p:{'contests':[],'updated_at':None,'stale':False,'error':'unavailable'} for p in ['codeforces','atcoder','nowcoder','luogu','leetcode']}
        with patch('club.contest_views.refresh_calendar',return_value=snapshots) as refresh:
            self.assertEqual(self.client.get('/api/contests?refresh=1').status_code,200)
        refresh.assert_called_once_with()
