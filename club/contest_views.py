"""Public contest calendars, fetched server-side without user credentials."""
import html
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.parse import urljoin
from urllib.request import Request, build_opener

from django.db import transaction, connections, close_old_connections
from .models import ContestCalendarSnapshot
from django.http import JsonResponse
from django.utils import timezone

from .daily_views import NoRedirect
from .views import api_login_required

logger = logging.getLogger(__name__)
PLATFORMS = {'codeforces': 'Codeforces', 'atcoder': 'AtCoder', 'nowcoder': '牛客', 'luogu': '洛谷', 'leetcode': 'LeetCode'}
BASES = {'codeforces': 'https://codeforces.com/contest/', 'atcoder': 'https://atcoder.jp/contests/',
         'nowcoder': 'https://ac.nowcoder.com/acm/contest/', 'luogu': 'https://www.luogu.com.cn/contest/', 'leetcode': 'https://leetcode.cn/contest/'}
LUOGU_CALENDAR_URL = 'https://www.luogu.com.cn/contest/list?_contentOnly=1&page=1'
_luogu_cookies = CookieJar()
_luogu_cookie_lock = threading.Lock()


def read_calendar_response(response, limit=4 * 1024 * 1024):
    raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('oversized calendar')
    return raw.decode('utf-8')


def fetch_text(url, limit=4 * 1024 * 1024):
    req = Request(url, headers={'User-Agent': 'Mozilla/5.0 ClubContestCalendar/1.0', 'Accept': '*/*'})
    with build_opener(NoRedirect()).open(req, timeout=10) as response:
        return read_calendar_response(response, limit)


def fetch_luogu_calendar():
    """Accept Luogu's anonymous cookie; retry only its same-URL handshake."""
    with _luogu_cookie_lock:
        opener = build_opener(NoRedirect())
        for attempt in range(3):
            if attempt:
                time.sleep(0.3)
            req = Request(LUOGU_CALENDAR_URL, headers={
                'User-Agent': 'Mozilla/5.0 ClubContestCalendar/1.0',
                'Accept': 'application/json', 'x-lentille-request': 'content-only',
            })
            # CookieJar enforces domain, path, Secure and expiry rules. These
            # cookies originate from anonymous requests, never a user's session.
            _luogu_cookies.add_cookie_header(req)
            try:
                response = opener.open(req, timeout=10)
            except HTTPError as exc:
                if exc.code not in (301, 302, 303):
                    raise
                with exc:
                    _luogu_cookies.extract_cookies(exc, req)
                    issued = any(re.match(r'\s*C3VK=', cookie) for cookie in exc.headers.get_all('Set-Cookie', []))
                    location = exc.headers.get('Location')
                    same_url = bool(location) and urljoin(LUOGU_CALENDAR_URL, location) == LUOGU_CALENDAR_URL
                    probe = Request(LUOGU_CALENDAR_URL)
                    _luogu_cookies.add_cookie_header(probe)
                    usable = bool(re.search(r'(?:^|;\s*)C3VK=', probe.get_header('Cookie', '')))
                    if not (issued and same_url and usable):
                        raise
                if attempt == 2:
                    raise ValueError('Luogu anonymous cookie handshake exceeded retry limit')
                continue
            with response:
                _luogu_cookies.extract_cookies(response, req)
                return read_calendar_response(response)


def contest(platform, cid, title, start, end):
    cid = str(cid)
    if not re.fullmatch(r'[A-Za-z0-9_-]+', cid) or not isinstance(title, str) or not title.strip():
        raise ValueError('invalid identity')
    start, end = float(start), float(end)
    if not 0 < start < end < 32503680000:
        raise ValueError('invalid schedule')
    return {'id': platform + '-' + cid, 'platform': platform, 'name': title.strip(),
            'start': start, 'end': end, 'url': BASES[platform] + cid}


def parse_calendar(platform, raw):
    items = []
    if platform == 'codeforces':
        data = json.loads(raw)
        if data.get('status') != 'OK' or not isinstance(data.get('result'), list):
            raise ValueError('invalid Codeforces response')
        rows = data['result']
        convert = lambda c: contest(platform, c['id'], c['name'], c['startTimeSeconds'], c['startTimeSeconds'] + c['durationSeconds'])
    elif platform == 'leetcode':
        rows = json.loads(raw)['contests']
        convert = lambda c: contest(platform, c['title_slug'], c['title'], c['start_time'], c['start_time'] + c['duration'])
    elif platform == 'luogu':
        rows = json.loads(raw)['data']['contests']['result']
        convert = lambda c: contest(platform, c['id'], c['name'], c['startTime'], c['endTime'])
    elif platform == 'nowcoder':
        rows = re.findall(r'data-json="([^"]*)"', raw)
        def convert(row):
            c = json.loads(html.unescape(html.unescape(row)))
            return contest(platform, c['contestId'], c['contestName'], c['contestStartTime'] / 1000, c['contestEndTime'] / 1000)
    else:
        if 'contest-table-' not in raw:
            raise ValueError('AtCoder calendar missing')
        rows = re.findall(r'<tr\b[^>]*>(.*?)</tr>', raw, re.S)
        def convert(row):
            link = re.search(r'href=[\"\']/contests/([A-Za-z0-9_-]+)[\"\'][^>]*>(.*?)</a>', row, re.S)
            time = re.search(r'<time\b[^>]*>([^<]+)</time>', row)
            duration = re.search(r'<td[^>]*>\s*(\d{1,4}):(\d{2})\s*</td>', row)
            if not link or not time or not duration:
                raise ValueError('not a scheduled contest row')
            start = datetime.fromisoformat(html.unescape(time[1]).strip()).timestamp()
            seconds = (int(duration[1]) * 60 + int(duration[2])) * 60
            title = html.unescape(re.sub(r'<[^>]*>', '', link[2]))
            return contest(platform, link[1], title, start, start + seconds)
    if not isinstance(rows, list):
        raise ValueError('invalid contest list')
    for row in rows:
        try:
            items.append(convert(row))
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
    if not items:
        raise ValueError('no valid contests parsed')
    return list({c['id']: c for c in items}.values())


def fetch_platform(platform):
    if platform == 'leetcode':
        # This official endpoint includes rich descriptions for its full
        # history (~9 MB), despite offset/limit parameters. Keep a fixed cap.
        return parse_calendar(platform, fetch_text('https://leetcode.cn/contest/api/list/', 16 * 1024 * 1024))
    if platform == 'luogu':
        return parse_calendar(platform, fetch_luogu_calendar())
    endpoints = {
        'codeforces': ['https://codeforces.com/api/contest.list?gym=false'],
        'atcoder': ['https://atcoder.jp/contests/'],
        'nowcoder': ['https://ac.nowcoder.com/acm/contest/vip-index'],
        'leetcode': ['https://leetcode.cn/contest/api/list/'],
    }
    return [c for url in endpoints[platform] for c in parse_calendar(platform, fetch_text(url))]


def snapshot_data(row):
    if row is None:
        return {'contests': [], 'updated_at': None, 'stale': False, 'error': '等待后台更新'}
    return {'contests': row.contests, 'updated_at': row.updated_at.isoformat() if row.updated_at else None,
            'stale': bool(row.error and row.updated_at), 'error': row.error or None}


def platform_snapshot(platform, force=False):
    """Refresh one persisted source; manual requests retain the original TTL."""
    ContestCalendarSnapshot.objects.get_or_create(platform=platform)
    with transaction.atomic():
        row = ContestCalendarSnapshot.objects.select_for_update().get(platform=platform)
        now = timezone.now()
        ttl = 60 if row.error else 900
        if not force and row.attempted_at and row.attempted_at > now - timedelta(seconds=ttl):
            return snapshot_data(row)
        try:
            row.contests = fetch_platform(platform)
            row.updated_at = timezone.now()
            row.error = ''
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            logger.warning('Contest calendar %s failed: %s', platform, type(exc).__name__)
            row.error = '暂时无法更新，显示上次数据' if row.updated_at else '暂时无法获取赛程'
        row.attempted_at = timezone.now()
        row.save()
        return snapshot_data(row)


def refresh_calendar(force=False):
    def refresh(platform):
        close_old_connections()
        try:
            return platform_snapshot(platform, force=force)
        finally:
            connections.close_all()
    with ThreadPoolExecutor(max_workers=4) as pool:
        return dict(zip(PLATFORMS, pool.map(refresh, PLATFORMS)))


@api_login_required
def contest_calendar(request):
    if request.method != 'GET':
        return JsonResponse({'error': '仅支持 GET'}, status=405)
    if request.GET.get('refresh') == '1':
        snapshots = refresh_calendar()
    else:
        saved = {row.platform: row for row in ContestCalendarSnapshot.objects.all()}
        snapshots = {platform: snapshot_data(saved.get(platform)) for platform in PLATFORMS}
    now = timezone.now().timestamp()
    contests, sources = [], []
    for platform, snapshot in snapshots.items():
        contests.extend(c for c in snapshot['contests'] if c['end'] >= now - 7 * 86400 and c['start'] <= now + 90 * 86400)
        sources.append({'platform': platform, 'name': PLATFORMS[platform],
                        **{k: snapshot[k] for k in ('updated_at', 'stale', 'error')}})
    return JsonResponse({'contests': sorted(contests, key=lambda c: c['start']), 'sources': sources,
                         'server_time': now, 'timezone': 'Asia/Shanghai'})
