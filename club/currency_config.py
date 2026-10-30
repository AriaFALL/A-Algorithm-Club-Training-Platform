"""Validated team currency settings shared by both management endpoints."""
import re
import base64
import binascii
from io import BytesIO
import uuid
import xml.etree.ElementTree as ET
from PIL import Image

from django.core.files.base import ContentFile

from .models import StreakReward, ContestRewardConfig, default_problem_rewards


def currency_icon_url(team):
    return f'/api/currency/icon/{team.pk}' if team.currency_icon else None


def config_data(team):
    return {
        'currency_enabled': team.currency_enabled,
        'currency_icon': currency_icon_url(team),
        'daily_checkin_reward': team.daily_checkin_reward,
        'streak_rewards': list(team.streak_rewards.values('days', 'reward')),
        'contest_rewards': list(team.contest_reward_configs.values('problems_solved', 'reward', 'is_ak')),
        'problem_rewards': team.problem_rewards or default_problem_rewards(),
    }


def validate_config(data):
    def integer(value, label, minimum=0, maximum=100000):
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f'{label}必须为 {minimum}–{maximum} 的整数')
    if 'currency_enabled' in data and type(data['currency_enabled']) is not bool:
        raise ValueError('货币开关必须为布尔值')
    if 'daily_checkin_reward' in data:
        integer(data['daily_checkin_reward'], '每日签到奖励', maximum=100)
    if 'problem_rewards' in data:
        rewards = data['problem_rewards']
        if not isinstance(rewards, dict) or set(rewards) != {'beginner', 'experienced'}:
            raise ValueError('请设置萌新与老登的三档奖励')
        for group in rewards.values():
            if not isinstance(group, list) or len(group) != 3:
                raise ValueError('每类需要三档奖励')
            for amount in group:
                integer(amount, '每题奖励', maximum=100000)
    for field in ('streak_rewards', 'contest_rewards'):
        if field not in data:
            continue
        rows = data[field]
        if not isinstance(rows, list) or len(rows) > 50:
            raise ValueError('奖励规则最多 50 条')
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('奖励规则格式无效')
            integer(row.get('reward'), '奖励金额', minimum=1)
            if field == 'streak_rewards':
                integer(row.get('days'), '连签天数', minimum=1, maximum=7)
                key = row['days']
            else:
                if type(row.get('is_ak')) is not bool:
                    raise ValueError('AK 类型无效')
                integer(row.get('problems_solved'), '过题数', minimum=0 if row['is_ak'] else 1)
                key = 'ak' if row['is_ak'] else row['problems_solved']
            if key in seen:
                raise ValueError('同一天数、过题数或 AK 奖励不能重复')
            seen.add(key)
    if 'currency_icon_svg' in data and data['currency_icon_svg'] is not None:
        raw = data['currency_icon_svg']
        if not isinstance(raw, str):
            raise ValueError('SVG 图标格式无效')
        if re.search(r'<!DOCTYPE|<!ENTITY', raw, re.I):
            raise ValueError('SVG 图标不能包含外部实体')
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            raise ValueError('SVG 图标格式无效')
        allowed = {'svg','g','defs','path','rect','circle','ellipse','line','polyline','polygon',
                   'linearGradient','radialGradient','stop','clipPath','mask','use','symbol','title','desc','image'}
        if root.tag.split('}')[-1] != 'svg':
            raise ValueError('请上传 SVG 图标')
        for node in root.iter():
            if node.tag.split('}')[-1] not in allowed:
                raise ValueError('SVG 仅支持静态图形，不支持脚本、样式表或嵌入内容')
            for key, value in node.attrib.items():
                attr = key.split('}')[-1].lower()
                embedded_image = False
                if node.tag.split('}')[-1] == 'image' and attr == 'href' and value.startswith('data:'):
                    match = re.fullmatch(r'data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=\s]+)', value)
                    if not match:
                        raise ValueError('SVG 内嵌图片仅支持 PNG、JPEG 或 WebP')
                    try:
                        content = base64.b64decode(re.sub(r'\s+', '', match[2]), validate=True)
                        with Image.open(BytesIO(content)) as image:
                            if image.format != {'png':'PNG', 'jpeg':'JPEG', 'webp':'WEBP'}[match[1]] or getattr(image, 'is_animated', False):
                                raise ValueError('invalid static image')
                            image.verify()
                    except (ValueError, binascii.Error, OSError, SyntaxError, Image.DecompressionBombError):
                        raise ValueError('SVG 内嵌图片格式无效')
                    embedded_image = True
                urls = re.findall(r'url\((.*?)\)', value, re.I)
                if attr.startswith('on') or (attr in ('href','src') and not value.startswith('#') and not embedded_image) or re.search(r'@import|expression\(', value, re.I) or any(not url.strip(" \t\r\n\"'").startswith('#') for url in urls):
                    raise ValueError('SVG 图标不能包含脚本或外部资源')


def apply_config(team, data):
    """Call after validation, inside a transaction holding the team row lock."""
    enabling = data.get('currency_enabled', team.currency_enabled) and not team.currency_enabled
    if enabling:
        from .currency_services import initialize_default_currency_config
        if not team.shop_items.exists() and not team.streak_rewards.exists() and not team.contest_reward_configs.exists():
            initialize_default_currency_config(team)
    for field in ('currency_enabled', 'daily_checkin_reward', 'problem_rewards'):
        if field in data:
            setattr(team, field, data[field])
    if 'currency_icon_svg' in data:
        if data['currency_icon_svg'] is None:
            team.currency_icon = ''
        else:
            team.currency_icon.save(f'{uuid.uuid4().hex}.svg', ContentFile(data['currency_icon_svg'].encode('utf-8')), save=False)
    team.save()
    if 'streak_rewards' in data:
        team.streak_rewards.all().delete()
        StreakReward.objects.bulk_create([StreakReward(team=team, days=r['days'], reward=r['reward']) for r in data['streak_rewards']])
    if 'contest_rewards' in data:
        team.contest_reward_configs.all().delete()
        ContestRewardConfig.objects.bulk_create([ContestRewardConfig(team=team, problems_solved=max(1,r['problems_solved']), reward=r['reward'], is_ak=r['is_ak']) for r in data['contest_rewards']])
