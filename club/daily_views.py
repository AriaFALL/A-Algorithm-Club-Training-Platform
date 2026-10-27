"""Daily challenge links obtained from fixed public platform endpoints."""
import json
import re
import threading
from datetime import timedelta
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler

from django.core.cache import cache
from django.http import JsonResponse
from django.utils import timezone

from .views import api_login_required


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_lock = threading.Lock()
LEETCODE_QUERY = 'query { todayRecord { date question { titleSlug } } }'


def fetch_leetcode(today):
    # No user supplied URL, cookies or credentials leave this application.
    url = 'https://leetcode.cn/graphql/?' + urlencode({'query': LEETCODE_QUERY})
    req = Request(url, headers={'Accept': 'application/json', 'User-Agent': 'ClubDailyChallenge/1.0'})
    with build_opener(NoRedirect()).open(req, timeout=8) as response:
        raw = response.read(65537)
    if len(raw) > 65536:
        raise ValueError('response too large')
    data = json.loads(raw)
    for record in data.get('data', {}).get('todayRecord', []):
        slug = record.get('question', {}).get('titleSlug', '')
        if record.get('date') == today and re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug):
            return 'https://leetcode.cn/problems/' + slug + '/'
    raise ValueError('no current daily challenge')


@api_login_required
def daily_links(request):
    if request.method != 'GET':
        return JsonResponse({'error': '仅支持 GET'}, status=405)
    today = timezone.localdate().isoformat()
    key = 'daily-challenge:leetcode:' + today
    result = cache.get(key)
    if result is None:
        with _lock:
            result = cache.get(key)
            if result is None:
                try:
                    result = {'url': fetch_leetcode(today)}
                    tomorrow = timezone.make_aware(timezone.datetime.combine(timezone.localdate() + timedelta(days=1), timezone.datetime.min.time()))
                    ttl = max(1, min(3600, int((tomorrow - timezone.now()).total_seconds())))
                except (ValueError, TypeError, KeyError, AttributeError, OSError):
                    result = {'url': None, 'error': '力扣每日一题暂时无法获取，请稍后重试'}
                    ttl = 60
                cache.set(key, result, ttl)
    return JsonResponse({'date': today, 'leetcode': result})
