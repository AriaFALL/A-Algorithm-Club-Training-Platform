"""Bounded OJ profile adapters, based on OJ-Insight's documented source flows.

Only fixed HTTPS origins are contacted. Secrets never enter URLs or errors.
Submission summaries are explicitly scoped when a full history isn't fetched.
"""
import json
import re
import time
from urllib.parse import quote, unquote, urlparse, urljoin

import requests
from bs4 import BeautifulSoup

PLATFORMS = {
    'codeforces': {'name': 'Codeforces', 'short': 'CF', 'hint': 'Handle'},
    'atcoder': {'name': 'AtCoder', 'short': 'AT', 'hint': '用户名'},
    'nowcoder': {'name': '牛客', 'short': 'NC', 'hint': '个人主页中的数字 UID'},
    'luogu': {'name': '洛谷', 'short': 'LG', 'hint': '数字 UID 或用户名'},
    'leetcode': {'name': 'LeetCode', 'short': 'LC', 'hint': '国际站用户名；中国站填写 cn:用户名'},
}
HOSTS = {'codeforces.com', 'atcoder.jp', 'kenkoooo.com', 'ac.nowcoder.com',
         'www.luogu.com.cn', 'leetcode.cn', 'leetcode.com', 'raw.githubusercontent.com', 'www.nowcoder.com'}


class SyncError(ValueError):
    pass


def validate_account(platform, account):
    if not isinstance(account, str) or not account.strip() or len(account.strip()) > 100:
        raise ValueError('请输入有效账号（最多 100 个字符）')
    account = account.strip()
    pattern = r'[1-9][0-9]{0,19}' if platform == 'nowcoder' else r'[\w.\-\u4e00-\u9fff]+'
    if platform == 'leetcode' and account.startswith('cn:'):
        check = account[3:]
    else:
        check = account
    if check in {'.', '..'} or not re.fullmatch(pattern, check):
        raise ValueError('请输入用户名或 UID，不要填写网址；牛客需填写数字 UID')
    return account


class Remote:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0 (compatible; ClubTraining/1.0)',
                                     'Accept': 'application/json,text/html;q=0.9'})
        self.deadline = time.monotonic() + 140

    def text(self, url, *, payload=None, headers=None, redirects=0, limit=8 * 1024 * 1024):
        if urlparse(url).scheme != 'https' or urlparse(url).hostname not in HOSTS:
            raise SyncError('不支持的平台地址')
        if time.monotonic() > self.deadline:
            raise SyncError('平台同步超时，请稍后重试')
        try:
            with self.session.request('POST' if payload is not None else 'GET', url,
                    json=payload, headers=headers, timeout=(5, 15), stream=True,
                    allow_redirects=False) as response:
                if response.status_code in {301, 302, 303, 307, 308} and payload is None and redirects < 3:
                    target = urljoin(url, response.headers.get('Location', ''))
                    if urlparse(target).hostname == urlparse(url).hostname and urlparse(target).scheme == 'https':
                        response.close()
                        return self.text(target, headers=headers, redirects=redirects + 1, limit=limit)
                if response.status_code != 200:
                    raise SyncError(f'平台返回 HTTP {response.status_code}，账号可能不存在、凭据失效或访问受限')
                chunks = []; size = 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > limit or time.monotonic() > self.deadline:
                        raise SyncError('平台响应过大或超时，请稍后重试')
                    chunks.append(chunk)
                content = b''.join(chunks)
                try:
                    return content.decode('utf-8')
                except UnicodeDecodeError:
                    return content.decode('gb18030', errors='replace')
        except requests.RequestException:
            raise SyncError('平台连接失败，请稍后重试') from None

    def json(self, url, **kwargs):
        try:
            return json.loads(self.text(url, **kwargs))
        except json.JSONDecodeError:
            raise SyncError('平台未返回有效数据，可能需要验证或暂时不可用') from None


def rating_summary(rows):
    """Rows must already be in chronological order."""
    return {'rating': rows[-1]['rating'] if rows else None,
            'max_rating': max((r['rating'] for r in rows), default=None),
            'contests': len(rows), 'rating_history': rows[-20:]}


def optional(result, label, operation):
    try:
        result.update(operation())
    except (SyncError, KeyError, TypeError, ValueError):
        result.setdefault('notes', []).append(f'{label}暂未获取，已保留其他可用资料')


def codeforces(remote, account):
    handle = quote(account, safe='')
    def api(method, params):
        data = remote.json(f'https://codeforces.com/api/{method}?{params}')
        if data.get('status') != 'OK':
            raise SyncError('Codeforces 账号不存在或 API 暂不可用')
        return data['result']
    users = api('user.info', f'handles={handle}')
    if not users:
        raise SyncError('未找到 Codeforces 账号')
    user = users[0]
    result = {'display_name': user['handle'], 'profile_url': f'https://codeforces.com/profile/{handle}',
              'rating': user.get('rating'), 'max_rating': user.get('maxRating'), 'rank': user.get('rank')}
    def history():
        time.sleep(2.1)
        rows = api('user.rating', f'handle={handle}')
        rows.sort(key=lambda r: r['ratingUpdateTimeSeconds'])
        return rating_summary([{'rating': r['newRating'], 'name': r['contestName']} for r in rows])
    optional(result, '比赛历史', history)
    def solved():
        time.sleep(2.1)
        rows = api('user.status', f'handle={handle}&from=1&count=1000')
        accepted = [r for r in rows if r.get('verdict') == 'OK']
        keys = {(r['problem'].get('contestId'), r['problem'].get('index'), r['problem'].get('name')) for r in accepted}
        return {'solved': len(keys), 'solved_label': '最近 1000 次提交中的去重 AC' if len(rows) == 1000 else '公开提交去重 AC',
                'accepted_submissions': len(accepted)}
    optional(result, '做题统计', solved)
    return result


def atcoder(remote, account):
    handle = quote(account, safe='')
    rows = remote.json(f'https://atcoder.jp/users/{handle}/history/json')
    if not isinstance(rows, list) or any('IsRated' not in r for r in rows):
        raise SyncError('AtCoder 账号不存在或比赛历史格式异常')
    # Verify the profile too: history endpoints can return [] for unknown users.
    profile = remote.text(f'https://atcoder.jp/users/{handle}')
    if 'user-page' not in profile and f'/users/{account}/history' not in profile:
        raise SyncError('未能确认 AtCoder 个人主页')
    rows = sorted((r for r in rows if r['IsRated']), key=lambda r: r['EndTime'])
    result = {'display_name': account, 'profile_url': f'https://atcoder.jp/users/{handle}',
              **rating_summary([{'rating': r['NewRating'], 'name': r['ContestName']} for r in rows])}
    def solved():
        info = remote.json(f'https://kenkoooo.com/atcoder/atcoder-api/v3/user_info?user={handle}')
        count = info.get('accepted_count')
        if not isinstance(count, int):
            raise SyncError('做题统计格式异常')
        return {'solved': count, 'solved_label': 'AtCoder Problems 去重 AC'}
    optional(result, '做题统计', solved)
    return result


def leetcode(remote, account):
    china = account.startswith('cn:')
    user = account[3:] if china else account
    base = 'https://leetcode.cn' if china else 'https://leetcode.com'
    def graphql(query, variables, endpoint='/graphql/'):
        data = remote.json(base + endpoint, payload={'query': query, 'variables': variables},
                           headers={'Referer': base + '/', 'Origin': base})
        if data.get('errors') or not data.get('data'):
            raise SyncError('LeetCode 账号不存在或公开资料暂不可用')
        return data['data']
    if china:
        stats = graphql('query($userSlug:String!){userProfilePublicProfile(userSlug:$userSlug){username} userProfileUserQuestionProgress(userSlug:$userSlug){numAcceptedQuestions{difficulty count}}}', {'userSlug': user})
        progress = stats.get('userProfileUserQuestionProgress')
        if not stats.get('userProfilePublicProfile') or not progress or not isinstance(progress.get('numAcceptedQuestions'), list):
            raise SyncError('未找到力扣中国站账号或题目统计')
        counts = progress['numAcceptedQuestions']
    else:
        stats = graphql('query($username:String!){matchedUser(username:$username){username submitStatsGlobal{acSubmissionNum{difficulty count}}}}', {'username': user})
        if not stats.get('matchedUser'):
            raise SyncError('未找到 LeetCode 账号')
        counts = stats['matchedUser']['submitStatsGlobal']['acSubmissionNum']
    all_row = next((r['count'] for r in counts if r['difficulty'].lower() == 'all'), None)
    result = {'display_name': user, 'profile_url': base + '/u/' + quote(user, safe='') + '/',
              'solved': all_row if all_row is not None else sum(r['count'] for r in counts),
              'solved_label': '累计通过题数',
              'difficulty': [{'label': r['difficulty'], 'count': r['count']} for r in counts if r['difficulty'].lower() != 'all']}
    def ratings():
        argument = 'userSlug' if china else 'username'
        data = graphql('query($account:String!){userContestRankingHistory(' + argument + ':$account){attended rating contest{title startTime}}}',
                       {'account': user}, '/graphql/noj-go/' if china else '/graphql/')
        rows = data.get('userContestRankingHistory')
        if not isinstance(rows, list):
            raise SyncError('比赛历史暂不可用')
        rows = sorted((r for r in rows if r.get('attended')), key=lambda r: r['contest']['startTime'])
        return rating_summary([{'rating': round(r['rating']), 'name': r['contest']['title']} for r in rows])
    optional(result, '比赛 Rating', ratings)
    return result


def luogu(remote, account):
    headers = {'Referer': 'https://www.luogu.com.cn/', 'x-lentille-request': 'content-only'}
    def payload(url):
        text = remote.text(url, headers=headers)
        try:
            data = json.loads(text)
        except ValueError:
            match = re.search(r'decodeURIComponent\(("(?:[^"\\]|\\.)*")\)', text)
            if not match:
                raise SyncError('洛谷触发访问限制或页面格式发生变化')
            data = json.loads(unquote(json.loads(match[1])))
        return data.get('data', data.get('currentData', data))
    uid = account
    if not account.isascii() or not account.isdigit():
        data = payload('https://www.luogu.com.cn/api/user/search?keyword=' + quote(account, safe=''))
        user = next((u for u in data.get('users', []) if u.get('name', u.get('username', '')).casefold() == account.casefold()), None)
        if not user:
            raise SyncError('未找到完全匹配的洛谷用户，请使用数字 UID')
        uid = str(user.get('uid', user.get('id', '')))
    if not re.fullmatch(r'[0-9]+', uid):
        raise SyncError('洛谷 UID 无效')
    base = f'https://www.luogu.com.cn/user/{uid}'
    data = payload(base)
    user = data.get('user', {})
    if str(user.get('uid', user.get('id', ''))) != uid:
        raise SyncError('洛谷返回的用户信息不匹配')
    result = {'display_name': user.get('name', account), 'profile_url': base}
    if isinstance(data.get('elo'), list):
        rows = sorted(data['elo'], key=lambda r: r.get('time', 0))
        result.update(rating_summary([{'rating': r['rating'], 'name': (r.get('contest') or {}).get('name', 'Rated 比赛')} for r in rows if isinstance(r.get('rating'), (int, float)) and r['rating'] > 0]))
    def practice():
        data = payload(base + '/practice')
        if not isinstance(data.get('passed'), list):
            raise SyncError('通过题目列表暂不可用')
        return {'solved': len(data['passed']), 'solved_label': '累计通过题数'}
    optional(result, '做题统计', practice)
    return result


def nowcoder(remote, account):
    base = f'https://ac.nowcoder.com/acm/contest/profile/{account}'
    text = remote.text(base + '/practice-coding?languageCategoryFilter=-1&orderType=DESC&page=1&pageSize=200&statusTypeFilter=5', headers={'Referer': 'https://ac.nowcoder.com/'})
    if not re.search(r'window\.curUser\.id\s*=\s*[\"\']' + re.escape(account) + r'[\"\']', text):
        raise SyncError('牛客账号不可公开访问或页面不匹配')
    soup = BeautifulSoup(text, 'html.parser')
    links = soup.select('table a[href]')
    problems = {a['href'] for a in links if re.search(r'/acm/(?:problem/\d+|contest/\d+/[A-Za-z0-9]+)', a['href']) and '/status/' not in a['href']}
    result = {'display_name': account, 'profile_url': base,
              'solved': len(problems), 'solved_label': '最近一页 AC 记录中的去重题数',
              'notes': ['做题统计仅包含公开 AC 记录首屏，不代表全站累计题数']}
    if not soup.select('table'):
        result.pop('solved')
        result['notes'].append('公开提交表未能识别')
    def ratings():
        data = remote.json(f'https://ac.nowcoder.com/acm/contest/rating-history?uid={account}', headers={'Referer': base})
        if data.get('code') != 0:
            raise SyncError('牛客 Rating 暂不可用')
        rows = data.get('data')
        if isinstance(rows, dict):
            rows = next((rows[k] for k in ['list', 'records', 'ratingHistory', 'ratingList'] if isinstance(rows.get(k), list)), None)
        if not isinstance(rows, list):
            raise SyncError('比赛历史格式异常')
        rows.sort(key=lambda r: float(r.get('time', r.get('contestTime', r.get('startTime', 0)))))
        unique = {}
        for r in rows:
            value = next((r[k] for k in ['rating', 'ratingValue', 'newRating'] if r.get(k) is not None), None)
            if value is not None:
                unique[str(r.get('contestId', r.get('id', len(unique))))] = {'rating': round(float(value)), 'name': r.get('contestName', r.get('name', 'Rating 比赛'))}
        return rating_summary(list(unique.values()))
    optional(result, '比赛 Rating', ratings)
    return result


def fetch_snapshot(platform, account):
    remote = Remote()
    try:
        return {'codeforces': codeforces, 'atcoder': atcoder, 'leetcode': leetcode,
                'luogu': luogu, 'nowcoder': nowcoder}[platform](remote, account)
    finally:
        remote.session.close()
