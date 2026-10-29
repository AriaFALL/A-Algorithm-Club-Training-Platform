"""Public contest evidence adapters. Never infer official AC from a practice count.

Discovery and per-contest hydration run separately so old histories are retained
when a platform hides its scoreboard. OJ-Insight source attribution is in docs.
"""
import csv
import io
import math
import logging
import re
import time
import threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from urllib.parse import quote

from bs4 import BeautifulSoup
from django.core.cache import cache
from .platform_sync import Remote, SyncError

logger=logging.getLogger(__name__)

_cf_lock = threading.Lock()
_cf_last = 0.0


def time_value(value):
    try:
        value=float(value)
        if value>=1e12:value/=1000
        return value if math.isfinite(value) and value>0 else None
    except (TypeError,ValueError,OverflowError):return None


def stamp(value):
    return datetime.fromtimestamp(float(value), timezone.utc)


def cached(remote, url):
    key = 'contest-evidence:v1:' + url
    value = cache.get(key)
    if value is None:
        value = remote.json(url)
        cache.set(key, value, 3600)
    return value


def cf(remote, method, params=''):
    global _cf_last
    with _cf_lock:
        time.sleep(max(0, 2.1 - (time.monotonic() - _cf_last)))
        try:
            data = remote.json('https://codeforces.com/api/' + method + '?' + params,
                               limit=64 * 1024 * 1024 if method == 'contest.standings' else 8 * 1024 * 1024)
        finally:
            _cf_last = time.monotonic()
    if data.get('status') != 'OK':
        raise SyncError('Codeforces API 暂不可用')
    return data['result']


def header(key, title, url, start, end, source=None):
    return dict(contest_key=str(key), title=title[:300], url=url,
                starts_at=stamp(start), ends_at=stamp(end), source_data=source or {})


def lc_host(account):
    return ('https://leetcode.cn', account[3:], 'CN') if account.startswith('cn:') else ('https://leetcode.com', account, 'US')


def discover(remote, platform, account):
    user = quote(account, safe='')
    if platform == 'codeforces':
        history = cf(remote, 'user.rating', 'handle=' + user)
        contests = {c['id']: c for c in cf(remote, 'contest.list', 'gym=false')}
        # Include official unrated participation as well as rated history.
        keys = {r['contestId'] for r in history}
        offset = 1; evidence = {}
        while True:
            rows = cf(remote, 'user.status', f'handle={user}&from={offset}&count=10000')
            keys.update(r['contestId'] for r in rows if r.get('contestId') in contests and
                        r.get('author', {}).get('participantType') in {'CONTESTANT', 'OUT_OF_COMPETITION'})
            for s in rows:
                if s.get('contestId') not in contests or s.get('verdict') != 'OK' or s.get('author', {}).get('participantType') not in {'CONTESTANT','OUT_OF_COMPETITION'}:
                    continue
                if not any(m.get('handle','').casefold() == account.casefold() for m in s.get('author', {}).get('members', [])):
                    continue
                evidence.setdefault(s['contestId'], []).append({'label':s['problem']['index'],'time':s.get('creationTimeSeconds')})
            if len(rows) < 10000:
                break
            offset += len(rows)
        return [header(c['id'], c['name'], f"https://codeforces.com/contest/{c['id']}",
                       c['startTimeSeconds'], c['startTimeSeconds'] + c['durationSeconds'], {'verified_submissions':evidence.get(key,[])})
                for key in keys if (c := contests.get(key)) and c.get('startTimeSeconds')]
    if platform == 'atcoder':
        history = remote.json(f'https://atcoder.jp/users/{user}/history/json')
        if not isinstance(history, list):
            raise SyncError('AtCoder 比赛历史不可用')
        contests = {c['id']: c for c in cached(remote, 'https://kenkoooo.com/atcoder/resources/contests.json')}
        return [header(c['id'], c['title'], 'https://atcoder.jp/contests/' + c['id'],
                       c['start_epoch_second'], c['start_epoch_second'] + c['duration_second'])
                for r in history if (c := contests.get(r.get('ContestScreenName', '').removesuffix('.contest.atcoder.jp')))]
    if platform == 'leetcode':
        host, user, region = lc_host(account)
        arg = 'userSlug' if region == 'CN' else 'username'
        query = 'query($u:String!){userContestRankingHistory(' + arg + ':$u){attended ranking contest{title startTime}}}'
        data = remote.json(host + ('/graphql/noj-go/' if region == 'CN' else '/graphql/'),
                           payload={'query': query, 'variables': {'u': user}})
        rows = (data.get('data') or {}).get('userContestRankingHistory')
        if not isinstance(rows, list):
            raise SyncError('LeetCode 比赛历史暂不可用')
        result = []
        for r in rows:
            if not r.get('attended'):
                continue
            title = r['contest']['title']; match = re.search(r'\d+', title)
            if not match:
                continue
            slug = ('biweekly' if '双周' in title or 'biweekly' in title.lower() else 'weekly') + '-contest-' + match[0]
            start = r['contest']['startTime']
            result.append(header(slug, title, host + '/contest/' + slug + '/', start, start + 5400,
                                 {'rank': r['ranking']}))
        return result
    if platform == 'nowcoder':
        history = remote.json('https://ac.nowcoder.com/acm/contest/rating-history?uid=' + user)
        rating_rows = history.get('data', [])
        if isinstance(rating_rows, dict):
            rating_rows = next((rating_rows[k] for k in ['list','records','ratingHistory','ratingList'] if isinstance(rating_rows.get(k),list)), [])
        keys = {str(r.get('contestId',r.get('contest_id',r.get('id','')))) for r in rating_rows}
        keys.discard(''); page = 1; seen_pages = set()
        while True:
            html = remote.text(f'https://ac.nowcoder.com/acm/contest/profile/{user}/join-index?page={page}')
            soup = BeautifulSoup(html, 'html.parser')
            found = set(re.findall(r'/acm/contest/(\d+)(?:["/?#]|$)', str(soup.select('table'))))
            signature = tuple(sorted(found))
            if not found or signature in seen_pages:
                break
            seen_pages.add(signature)
            keys |= found
            if not soup.select('a[rel="next"]') and not any(a.get_text(strip=True) in ['下一页', '>'] for a in soup.select('.pagination a')):
                break
            page += 1
        result = []
        for key in keys:
            c = remote.json('https://ac.nowcoder.com/acm/contest/contest-info?id=' + key).get('data') or {}
            if c.get('startTime') and c.get('endTime'):
                result.append(header(key, c['name'], 'https://ac.nowcoder.com/acm/contest/' + key,
                                     c['startTime']/1000, c['endTime']/1000))
        if not keys and 'curUser' not in html and history.get('code') != 0:
            raise SyncError('牛客参赛历史暂不可公开读取')
        return result
    if platform == 'luogu':
        from .platform_sync import luogu
        try:cookie = configure_luogu(remote)
        except SyncError as exc:
            logger.warning('Luogu timing credentials unavailable: %s',str(exc)[:160]);cookie=''
        profile = luogu(remote, account)
        data = remote.json(profile['profile_url'], headers={'x-lentille-request': 'content-only'})
        data = data.get('data', data.get('currentData', data))
        result = []
        for r in data.get('elo', []):
            key = str((r.get('contest') or {}).get('id', ''))
            if not key:
                continue
            d = remote.json('https://www.luogu.com.cn/contest/' + key, headers={'x-lentille-request':'content-only'})
            c = d.get('data', d.get('currentData', d)).get('contest', {})
            if c.get('startTime') and c.get('endTime'):
                result.append(header(key, c['name'], 'https://www.luogu.com.cn/contest/' + key,
                                     c['startTime'], c['endTime']))
        return result
    raise SyncError('不支持此平台')


def problem(key, label, title, url, difficulty=None, source='', ac=None):
    try:
        difficulty = float(difficulty) if difficulty is not None else None
        if difficulty is not None and not math.isfinite(difficulty):
            difficulty = None
    except (TypeError, ValueError):
        difficulty = None
    return dict(problem_key=str(key), label=str(label), title=title[:300], url=url,
                difficulty=difficulty, difficulty_source=source if difficulty is not None else '',
                accepted=ac is not None, official_ac=ac is not None, accepted_at=stamp(ac) if ac is not None else None)


def relaxed_ac(row, accepted):
    # Keep unknown time distinct from verified official time. Reward policy
    # grants proven AC via the user-requested relaxed fallback.
    if accepted:
        row.update(accepted=True, official_ac=False, accepted_at=None)
    return row


def configure_luogu(remote):
    from .models import ParserSettings
    from .problem_parser import key_cipher
    config = ParserSettings.objects.filter(pk=1).first()
    if not config or not config.encrypted_luogu_cookie:
        return ''
    try:
        cookie = key_cipher().decrypt(config.encrypted_luogu_cookie.encode()).decode()
    except Exception:
        raise SyncError('洛谷 Cookie 无法解密，请重新保存') from None
    pairs = dict(part.strip().split('=',1) for part in cookie.split(';') if '=' in part)
    if not pairs.get('_uid','').isdigit() or not pairs.get('__client_id'):
        raise SyncError('请系统管理员配置有效的洛谷查询 Cookie')
    for name in ('_uid','__client_id'):
        remote.session.cookies.set(name,pairs[name],domain='www.luogu.com.cn',path='/',secure=True)
    return cookie


def luogu_ac_times(remote, uid, cookie, since, contest_key=None, other_evidence=None, evidence=None):
    """Read the authenticated Lentille record list, independently implemented.

    Protocol reference: icpc-workbench luogu adapter. Missing timestamps remain
    unknown; they are never replaced with the current time.
    """
    pairs = dict(part.strip().split('=', 1) for part in cookie.split(';') if '=' in part)
    if not pairs.get('_uid','').isdigit() or not pairs.get('__client_id'):
        raise SyncError('请系统管理员配置有效的洛谷查询 Cookie')
    for name in ('_uid', '__client_id'):
        remote.session.cookies.set(name, pairs[name], domain='www.luogu.com.cn', path='/', secure=True)
    result = evidence if evidence is not None else {}; seen = set()
    for page in range(1, 101):
        if page > 1:
            time.sleep(0.5)
        data = remote.json(f'https://www.luogu.com.cn/record/list?user={uid}&page={page}',
                           headers={'x-lentille-request':'content-only','Referer':'https://www.luogu.com.cn/'})
        payload = data.get('data', data.get('currentData', {}))
        rows = (payload.get('records') or {}).get('result')
        if not isinstance(rows, list):
            raise SyncError('洛谷提交记录暂不可读取，请检查 Cookie 是否有效')
        if not rows:
            return result
        signature = tuple(str(r.get('id')) for r in rows)
        if signature in seen:
            raise SyncError('洛谷提交记录分页未能继续')
        seen.add(signature)
        times = []
        for row in rows:
            owner = row.get('user') or {}
            if str(owner.get('uid','')) != str(uid):
                raise SyncError('洛谷提交记录账号不匹配')
            value = row.get('submitTime')
            try:
                value = float(value)
                if value >= 1e12:
                    value /= 1000
                if not math.isfinite(value) or value <= 0:
                    value = None
            except (TypeError, ValueError):
                value = None
            if value is not None:
                times.append(value)
            pid = (row.get('problem') or {}).get('pid')
            record_contest = row.get('contest') or {}
            same_contest = contest_key is None or str(record_contest.get('id')) == str(contest_key)
            if row.get('status') == 12 and pid:
                if same_contest:result.setdefault(pid, []).append(value)
                elif other_evidence is not None:other_evidence.setdefault(pid,[]).append(value)
        if len(times) == len(rows) and max(times) < since:
            return result
    raise SyncError('洛谷历史记录过多，本次未能完整核验比赛时段')


def nowcoder_ratings(remote):
    values = cache.get('nc-tracker-ratings:v2')
    if values is not None:
        return values
    values = {}; seen = set(); page = 1; fetched = 0
    try:
        while True:
            data = remote.json(f'https://www.nowcoder.com/problem/tracker/list?contestType=0&page={page}&pageSize=200&limit=200',
                               headers={'Referer':'https://www.nowcoder.com/problem/tracker'})
            if data.get('code') not in (0,200):
                break
            data = data.get('data') or {}
            papers = next((data[k] for k in ['papers','list','records','result'] if isinstance(data.get(k),list)), [])
            signature = str(papers)
            if not papers or signature in seen:
                break
            seen.add(signature)
            for paper in papers:
                questions = next((paper[k] for k in ['questions','problems','questionList','problemList'] if isinstance(paper.get(k),list)), [])
                for p in questions:
                    key = p.get('problemId',p.get('questionId',p.get('id')))
                    difficulty = p.get('difficulty',p.get('difficultyScore',p.get('rating')))
                    if key is not None and difficulty is not None:
                        difficulty = int(difficulty)
                        if difficulty > 0:
                            values[str(key)] = {1:800,2:1200,3:1600,4:2000,5:2400,6:2800,7:3000,8:3200,9:3400,10:3500}.get(difficulty,difficulty)
            fetched += len(papers)
            total = data.get('totalCount')
            if isinstance(total,int) and fetched >= total:
                break
            page += 1
    except (SyncError, ValueError, TypeError):
        pass
    cache.set('nc-tracker-ratings:v2', values, 3600 if values else 300)
    return values


def nowcoder_accepted(remote, account):
    cache_key = 'nc-accepted:v2:' + account
    existing = cache.get(cache_key)
    if existing is not None:
        return existing
    accepted = {}; page = 1; seen = set()
    while True:
        html = remote.text(f'https://ac.nowcoder.com/acm/contest/profile/{account}/practice-coding?languageCategoryFilter=-1&orderType=DESC&page={page}&pageSize=200&search=&statusTypeFilter=5')
        if not re.search(r'window\.curUser\.id\s*=\s*["\']'+re.escape(account)+r'["\']', html):
            raise SyncError('牛客公开 AC 记录账号不匹配')
        soup = BeautifulSoup(html, 'html.parser'); rows = [tr for tr in soup.select('table tr') if tr.select('td')]
        signature = str(rows)
        if signature in seen:
            raise SyncError('牛客 AC 分页未能继续，请稍后重试')
        seen.add(signature)
        for tr in rows:
            cells = tr.select('td')
            verdict = cells[2].get_text(strip=True).lower() if len(cells) >= 3 else ''
            if not ('答案正确' in verdict or 'accepted' in verdict or verdict == 'ac'):
                continue
            date = re.search(r'20\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?', tr.get_text(' ',strip=True))
            try:timestamp = datetime.fromisoformat(date[0]).replace(tzinfo=ZoneInfo('Asia/Shanghai')).timestamp() if date else None
            except ValueError:timestamp=None
            for a in tr.select('a[href]'):
                m = re.search(r'/acm/(problem/\d+|contest/\d+/[A-Za-z0-9]+)(?:[/?#]|$)', a['href'])
                if m:
                    accepted.setdefault(m[1], []).append(timestamp)
        has_next = bool(soup.select('a[rel=next]')) or any(a.get_text(strip=True) in ['下一页','>','›'] and 'disabled' not in (a.parent.get('class') or []) for a in soup.select('.pagination a'))
        if not has_next and len(rows) < 200:
            break
        page += 1
    cache.set(cache_key, accepted, 300)
    return accepted


def hydrate(remote, contest):
    platform, key, account = contest.platform, quote(contest.contest_key, safe=''), contest.account
    start, end = contest.starts_at.timestamp(), contest.ends_at.timestamp()
    if platform == 'codeforces':
        evidence = getattr(contest, 'source_data', {}).get('verified_submissions')
        if isinstance(evidence, list):
            catalog = cache.get('cf-problems-by-contest:v1')
            if catalog is None:
                catalog = {}
                for p in cf(remote, 'problemset.problems')['problems']:
                    if 'contestId' in p:
                        catalog.setdefault(str(p['contestId']), []).append(p)
                cache.set('cf-problems-by-contest:v1', catalog, 3600)
            tasks = catalog.get(contest.contest_key)
            if tasks:
                accepted = {}
                for s in evidence:
                    t = time_value(s.get('time'))
                    if t is None:
                        accepted.setdefault(s['label'],None)
                    elif start <= t < end:
                        accepted[s['label']] = min(t,accepted.get(s['label']) or t)
                return [relaxed_ac(problem(p['index'],p['index'],p['name'],contest.url+'/problem/'+p['index'],
                                           p.get('rating'),'Codeforces rating',accepted.get(p['index'])),
                                   p['index'] in accepted and accepted[p['index']] is None) for p in sorted(tasks,key=lambda p:p['index'])], ''
        # Current CF requires anonymous standings requests with contestId only.
        data = cf(remote, 'contest.standings', f'contestId={key}')
        official = [r for r in data['rows'] if r['party']['participantType'] in {'CONTESTANT','OUT_OF_COMPETITION'} and
                    any(m['handle'].casefold() == account.casefold() for m in r['party']['members'])]
        submissions = cf(remote, 'contest.status', f'contestId={key}&handle={quote(account, safe="")}&from=1&count=10000')
        submissions = [s for s in submissions if s.get('author', {}).get('participantType') in {'CONTESTANT','OUT_OF_COMPETITION'}
                       and any(m.get('handle','').casefold() == account.casefold() for m in s.get('author', {}).get('members', []))]
        if not official and not submissions:
            raise SyncError('未找到实际参赛记录')
        accepted = {}
        for s in submissions:
            t = time_value(s.get('creationTimeSeconds'))
            if s.get('verdict') == 'OK':
                label = s['problem']['index']
                if t is None:
                    accepted.setdefault(label, None)
                elif start <= t < end:
                    accepted[label] = min(t, accepted.get(label) or t)
        return [relaxed_ac(problem(p['index'], p['index'], p['name'], contest.url + '/problem/' + p['index'],
                        p.get('rating'), 'Codeforces rating', accepted.get(p['index'])),
                        p['index'] in accepted and accepted[p['index']] is None) for p in data['problems']], ''
    if platform == 'atcoder':
        # problems.json reassigns reused problems to ADT contests. The original
        # contest's official tasks page is the authoritative complete roster.
        soup = BeautifulSoup(remote.text(contest.url + '/tasks'), 'html.parser')
        tasks = []
        for tr in soup.select('table tbody tr'):
            cells = tr.select('td')
            if len(cells) < 2:
                continue
            a = cells[0].select_one('a[href]')
            match = re.fullmatch(r'/contests/' + re.escape(contest.contest_key) + r'/tasks/([\w-]+)', a['href']) if a else None
            if match:
                tasks.append({'id':match[1], 'problem_index':a.get_text(strip=True), 'title':cells[1].get_text(strip=True)})
        models = cached(remote, 'https://kenkoooo.com/atcoder/resources/problem-models.json')
        accepted = {}; cursor = int(start); observed = False; timing_warning=''
        while cursor < end:
            rows = remote.json(f'https://kenkoooo.com/atcoder/atcoder-api/v3/user/submissions?user={quote(account, safe="")}&from_second={cursor}')
            if not isinstance(rows, list):
                raise SyncError('AtCoder 提交历史暂不可用')
            observed = observed or bool(rows)
            for s in rows:
                t = time_value(s.get('epoch_second'))
                if s.get('contest_id') == contest.contest_key and s.get('result') == 'AC':
                    if t is None:accepted.setdefault(s['problem_id'],None)
                    elif start<=t<end:accepted[s['problem_id']] = min(t,accepted.get(s['problem_id']) or t)
            if len(rows) < 500:
                break
            times=[t for s in rows if (t:=time_value(s.get('epoch_second'))) is not None]
            if not times:
                timing_warning='AtCoder 提交记录缺少时间，已确认 AC 按宽松规则处理';break
            next_cursor = int(max(times)) + 1
            if next_cursor <= cursor:
                raise SyncError('提交分页无法继续')
            cursor = next_cursor
        if not tasks:
            raise SyncError('题目清单暂不可用')
        result = []
        for p in tasks:
            difficulty = models.get(p['id'], {}).get('difficulty')
            if difficulty is not None and difficulty < 400:
                difficulty = 400 * math.exp((difficulty - 400)/400)
            result.append(relaxed_ac(problem(p['id'],p.get('problem_index',p['id']),p.get('name',p['title']),
                contest.url+'/tasks/'+p['id'],difficulty,'AtCoder Problems',accepted.get(p['id'])),p['id'] in accepted and accepted[p['id']] is None))
        return result, timing_warning or ('' if observed else 'AtCoder 提交镜像未提供该时段记录，暂无法完整核验赛内 AC')
    if platform == 'leetcode':
        host, user, region = lc_host(account)
        info = remote.json(host + '/contest/api/info/' + key + '/')
        meta = info['contest']
        if meta.get('is_virtual') or int(meta['start_time']) != int(start):
            raise SyncError('比赛时间或比赛身份不匹配')
        duration=float(meta['duration'])
        if not math.isfinite(duration) or duration<=0:raise SyncError('LeetCode 比赛时长无效')
        end=start+duration
        contest.ends_at=stamp(end)
        rank = int(contest.source_data['rank']); target = max(1, math.ceil(rank/25)); accepted = None
        for page in dict.fromkeys([target, max(1,target-1), target+1]):
            board = remote.json(host + f'/contest/api/ranking/{key}/?pagination={page}&region=global')
            for i, row in enumerate(board.get('total_rank', [])):
                if row.get('user_slug', '').casefold() == user.casefold() and row.get('data_region') == region:
                    accepted = board['submissions'][i]; break
            if accepted is not None:
                break
        if accepted is None:
            raise SyncError('未能在正式榜单核验账号，暂不发放奖励')
        ratings = cache.get('lc-problem-ratings:v1')
        if ratings is None:
            try:
                text = remote.text('https://raw.githubusercontent.com/zerotrac/leetcode_problem_rating/main/ratings.txt')
                ratings = {r['Title Slug']: float(r['Rating']) for r in csv.DictReader(io.StringIO(text), delimiter='\t')}
                cache.set('lc-problem-ratings:v1', ratings, 21600)
            except (SyncError, ValueError, KeyError):
                ratings = {}
        result = []
        for i, p in enumerate(info['questions']):
            s = accepted.get(str(p['question_id']), {})
            t = time_value(s.get('date'))
            ac = t if s.get('status') == 10 and t is not None and start<=t<end else None
            row = problem(p['title_slug'], 'Q'+str(i+1), p['title'], host+'/problems/'+p['title_slug']+'/',
                          ratings.get(p['title_slug']), 'zerotrac difficulty rating', ac)
            result.append(relaxed_ac(row, s.get('status') == 10 and t is None))
        return result, ''
    if platform == 'nowcoder':
        result = []; page = 1; accepted = nowcoder_accepted(remote, account); ratings = nowcoder_ratings(remote)
        while True:
            d = remote.json(f'https://ac.nowcoder.com/acm/contest/problem-list?id={key}&page={page}')['data']
            for p in d.get('data', []):
                label = str(p.get('index', p.get('problemIndex', '')))
                aliases = [f'contest/{contest.contest_key}/{label}', 'problem/'+str(p.get('problemId',''))]
                found = [t for a in aliases for t in accepted.get(a,[])]
                times = [t for t in found if t is not None and start <= t < end]
                t = min(times) if times else None
                row = problem(label, label, p.get('title', label), contest.url+'/'+label,
                              ratings.get(str(p.get('problemId')),p.get('rating')), '牛客 Tracker Rating', t if t is not None and start <= t < end else None)
                if found and not times:
                    known_times=[value for value in found if value is not None]
                    if any(value is None for value in found):relaxed_ac(row,True)
                    elif known_times:row.update(accepted=True,official_ac=False,accepted_at=stamp(min(known_times)))
                result.append(row)
            if page >= d.get('basicInfo', {}).get('pageCount', 1):
                break
            page += 1
        if not result:
            raise SyncError('牛客题目清单暂不可公开读取')
        return result, ''
    if platform == 'luogu':
        from .platform_sync import luogu
        try:cookie = configure_luogu(remote)
        except SyncError as exc:
            logger.warning('Luogu timing credentials unavailable: %s',str(exc)[:160]);cookie=''
        profile = luogu(remote, account)
        practice = remote.json(profile['profile_url']+'/practice', headers={'x-lentille-request':'content-only'})
        practice = practice.get('data', practice.get('currentData', practice))
        if not isinstance(practice.get('passed'), list):
            raise SyncError('洛谷公开 AC 清单暂不可读取')
        passed = {str(p.get('pid')) if isinstance(p, dict) else str(p) for p in practice['passed']}
        known = {}; other_evidence={}
        if cookie:
            uid = profile['profile_url'].rstrip('/').rsplit('/',1)[-1]
            try:known = luogu_ac_times(remote,uid,cookie,start,contest.contest_key,other_evidence,known)
            except SyncError as exc:
                logger.warning('Luogu timing unavailable; retaining proven AC fallback: %s',str(exc)[:160])
                # Retain already verified records even if a later page failed.
        d = remote.json(contest.url, headers={'x-lentille-request':'content-only'})
        data = d.get('data', d.get('currentData', d))
        result = []
        for i, row in enumerate(data.get('contestProblems', data.get('problems', []))):
            p = row.get('problem', row)
            evidence = known.get(p['pid'], [])
            outside_context=other_evidence.get(p['pid'],[])
            inside = [t for t in evidence if t is not None and start <= t < end]
            row = problem(p['pid'], row.get('no') or str(i+1), p.get('title',p.get('name',p['pid'])), 'https://www.luogu.com.cn/problem/'+p['pid'],
                          p.get('difficulty') or None, '洛谷难度等级', min(inside) if inside else None)
            if not inside and evidence and all(t is not None for t in evidence):
                row.update(accepted=True, official_ac=False, accepted_at=stamp(min(evidence)))
            elif not inside:
                known_outside=[t for t in outside_context if t is not None]
                if known_outside:row.update(accepted=True,official_ac=False,accepted_at=stamp(min(known_outside)))
                else:relaxed_ac(row,p['pid'] in passed or bool(evidence) or bool(outside_context))
            result.append(row)
        if not result:
            raise SyncError('洛谷题目清单暂不可公开读取')
        return result, ''
    raise SyncError('不支持此平台')
