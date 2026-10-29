"""
Currency system business logic
"""
from datetime import date, timedelta
from django.db import transaction,IntegrityError
import uuid
from django.utils import timezone

from .models import (
    CurrencyBalance, CurrencyTransaction, CheckinRecord,
    StreakReward, ContestRewardConfig, ShopItem, Purchase,
    UserInventory, TeamMembership, MakeupPermission, Semester
)


def positive_id(value):
    if isinstance(value,str) and len(value)<=19 and value.isdigit():value=int(value)
    if type(value) is not int or not 1<=value<=9223372036854775807:
        raise ValueError('编号必须为有效的正整数')
    return value


def get_or_create_balance(member):
    """Get or create currency balance for a member"""
    balance, created = CurrencyBalance.objects.get_or_create(
        team=member.team,
        member=member,
        defaults={"balance": 0}
    )
    return balance


@transaction.atomic
def add_currency(member, amount, transaction_type, description="", created_by=None):
    """Add currency to a member's balance"""
    if type(amount) is not int or amount < 0:
        raise ValueError("金额必须为非负整数")
    balance = get_or_create_balance(member)
    balance = CurrencyBalance.objects.select_for_update().get(pk=balance.pk)
    if balance.balance + amount > 2147483647:
        raise ValueError('RBC Coins 余额已达存储上限，请联系管理员')
    balance.balance += amount
    balance.save()

    CurrencyTransaction.objects.create(
        team=member.team,
        member=member,
        amount=amount,
        balance_after=balance.balance,
        transaction_type=transaction_type,
        description=description,
        created_by=created_by
    )

    return balance.balance


@transaction.atomic
def deduct_currency(member, amount, transaction_type, description="", created_by=None):
    """Deduct currency from a member's balance"""
    if type(amount) is not int or amount <= 0:
        raise ValueError("扣除金额必须为正整数")
    balance = get_or_create_balance(member)
    balance = CurrencyBalance.objects.select_for_update().get(pk=balance.pk)

    if balance.balance < amount:
        raise ValueError("余额不足")

    balance.balance -= amount
    balance.save()

    CurrencyTransaction.objects.create(
        team=member.team,
        member=member,
        amount=-amount,
        balance_after=balance.balance,
        transaction_type=transaction_type,
        description=description,
        created_by=created_by
    )

    return balance.balance


def signed_dates(member, start=None, end=None):
    from .models import Submission
    filters = {'member':member}
    checkins = CheckinRecord.objects.filter(**filters)
    submissions = Submission.objects.filter(**filters,is_valid=True)
    if start:
        checkins=checkins.filter(checkin_date__gte=start)
        submissions=submissions.filter(record_date__gte=start)
    end = min(end,timezone.localdate()) if end else timezone.localdate()
    return set(checkins.filter(checkin_date__lte=end).values_list('checkin_date',flat=True)) | set(submissions.filter(record_date__lte=end).values_list('record_date',flat=True))


def get_current_streak(member):
    today=timezone.localdate()
    dates=signed_dates(member)
    cursor=today if today in dates else today-timedelta(days=1)
    streak=0
    while cursor in dates:
        streak+=1
        cursor-=timedelta(days=1)
    return streak


@transaction.atomic
def perform_checkin(member):
    """Perform daily check-in"""
    today = timezone.localdate()
    if not member.pk:
        raise ValueError('仅团队成员可以签到')
    if not TeamMembership.objects.select_for_update().get(pk=member.pk).is_active:
        raise ValueError('当前成员权限已失效')

    # Check if already checked in today
    if CheckinRecord.objects.filter(team=member.team, member=member, checkin_date=today).exists():
        raise ValueError("今日已签到")

    # Create check-in record
    CheckinRecord.objects.create(
        team=member.team,
        member=member,
        checkin_date=today,
        is_makeup=False
    )

    # Award daily check-in reward
    daily_reward = member.team.daily_checkin_reward
    add_currency(member, daily_reward, CurrencyTransaction.CHECKIN, "每日签到")

    # Check for streak rewards
    streak = get_current_streak(member)
    weekly_bonus = settle_weekly_streak(member, today)

    return {"success": True, "streak": streak, "reward": daily_reward, "weekly_bonus": weekly_bonus}


@transaction.atomic
def makeup_checkin(member, checkin_date):
    """Spend one ticket to persist a single historical submission permission."""
    if checkin_date >= timezone.localdate():
        raise ValueError('补签请选择今天之前的日期')
    today = timezone.localdate()
    semester = Semester.objects.select_for_update().filter(team=member.team, is_active=True,
        archived_at__isnull=True, starts_on__lte=checkin_date, ends_on__gte=today).first()
    if not semester:
        raise ValueError('仅可补交当前学期内的历史日期')
    from .services import build_weeks
    build_weeks(semester)
    week = semester.weeks.filter(starts_at__date__lte=checkin_date, ends_at__date__gt=checkin_date).first()
    if not week:
        raise ValueError('该日期没有对应周次，请联系管理员')
    locked = TeamMembership.objects.select_for_update().get(pk=member.pk)
    if not locked.is_active:
        raise ValueError('当前团队成员权限已失效')
    from .models import Submission
    permission = MakeupPermission.objects.filter(member=member, semester=semester, record_date=checkin_date).first()
    if (permission and permission.completed_at or
            CheckinRecord.objects.filter(team=member.team, member=member, checkin_date=checkin_date).exists() or
            Submission.objects.filter(member=member, record_date=checkin_date, is_valid=True).exists()):
        raise ValueError('该日期已签到或已有有效提交，无需补签')
    from django.db.models import Sum
    def result(already_open):
        remaining = UserInventory.objects.filter(team=member.team, member=member,
            item__item_type='makeup_ticket', quantity__gt=0).aggregate(total=Sum('quantity'))['total'] or 0
        return {'success': True, 'remaining_tickets': remaining, 'checkin_date': checkin_date.isoformat(),
                'week_id': week.pk, 'already_open': already_open, 'completed': False}
    if permission:
        return result(True)
    inventory = UserInventory.objects.select_for_update(of=('self',)).filter(
        team=member.team, member=member, item__team=member.team,
        item__item_type='makeup_ticket', quantity__gt=0).order_by('pk').first()
    if not inventory:
        item = ShopItem.objects.filter(team=member.team, item_type='makeup_ticket',
                                       is_active=True).exclude(stock=0).order_by('price', 'pk').first()
        error = ValueError('没有可用补签券，请前往 RBC 商店购买')
        error.error_code = 'INSUFFICIENT_MAKEUP_TICKETS'
        error.item_id = item.pk if item else None
        error.item_name = item.name if item else '补签券'
        error.item_price = item.price if item else None
        raise error
    inventory.quantity -= 1
    inventory.save(update_fields=['quantity'])
    MakeupPermission.objects.create(member=member, semester=semester, record_date=checkin_date)
    return result(False)

@transaction.atomic
def purchase_item(member, item_id, quantity=1, request_id=None):
    """Purchase an item from the shop"""
    if type(quantity) is not int or not 1 <= quantity <= 100:
        raise ValueError("购买数量必须是 1–100 的整数")
    item_id=positive_id(item_id)
    if not TeamMembership.objects.select_for_update().get(pk=member.pk).is_active:
        raise ValueError('当前成员权限已失效')
    token=None
    if request_id is not None:
        try:token=uuid.UUID(str(request_id))
        except (ValueError,TypeError):raise ValueError('购买请求编号无效')
        prior=Purchase.objects.filter(request_id=token).first()
        if prior:
            if prior.member_id!=member.pk or prior.item_id!=item_id or prior.quantity!=quantity:
                raise ValueError('购买请求编号已被使用')
            return {'success':True,'total_price':prior.total_price,'duplicate':True}
    try:
        item = ShopItem.objects.select_for_update().get(pk=item_id, team=member.team, is_active=True)
    except ShopItem.DoesNotExist:
        raise ValueError("商品不存在或已下架")

    # Check stock
    if item.stock != -1 and item.stock < quantity:
        raise ValueError("库存不足")

    total_price = item.price * quantity

    # Deduct currency
    deduct_currency(member, total_price, CurrencyTransaction.PURCHASE, f"购买 {item.name} x{quantity}")

    # Update stock
    if item.stock != -1:
        item.stock -= quantity
        item.save()

    # Create purchase record
    try:
        with transaction.atomic():
            Purchase.objects.create(team=member.team,member=member,item=item,quantity=quantity,total_price=total_price,request_id=token)
    except IntegrityError:
        raise ValueError('购买请求编号已被使用') from None


    # Add to inventory for consumable items
    if item.item_type in ["makeup_ticket", "consumable"]:
        inventory, created = UserInventory.objects.get_or_create(
            team=member.team,
            member=member,
            item=item,
            defaults={"quantity": 0}
        )
        inventory = UserInventory.objects.select_for_update().get(pk=inventory.pk)
        inventory.quantity += quantity
        inventory.save()

    return {"success": True, "total_price": total_price}


def calculate_contest_reward(problems_solved, is_ak, team):
    """Calculate contest reward based on problems solved"""
    if is_ak:
        config = ContestRewardConfig.objects.filter(team=team, is_ak=True).first()
        return config.reward if config else 0

    # Find the highest applicable reward
    configs = ContestRewardConfig.objects.filter(
        team=team,
        is_ak=False,
        problems_solved__lte=problems_solved
    ).order_by('-problems_solved')

    if configs.exists():
        return configs.first().reward

    return 0


def get_transaction_history(member, limit=50):
    """Get transaction history for a member"""
    return CurrencyTransaction.objects.filter(
        team=member.team,
        member=member
    )[:limit]


def initialize_default_currency_config(team):
    """Initialize default currency configuration for a team"""
    # Create default streak rewards
    StreakReward.objects.get_or_create(
        team=team,
        days=7,
        defaults={"reward": 2}
    )
    StreakReward.objects.get_or_create(
        team=team,
        days=3,
        defaults={"reward": 1}
    )

    # Create default contest reward configs
    ContestRewardConfig.objects.get_or_create(
        team=team,
        problems_solved=2,
        defaults={"reward": 1, "is_ak": False}
    )
    ContestRewardConfig.objects.get_or_create(
        team=team,
        problems_solved=4,
        defaults={"reward": 2, "is_ak": False}
    )
    ContestRewardConfig.objects.get_or_create(
        team=team,
        problems_solved=1,
        defaults={"reward": 5, "is_ak": True}
    )

    # Create default makeup ticket item
    ShopItem.objects.get_or_create(
        team=team,
        item_type="makeup_ticket",
        defaults={
            "name": "补签券",
            "description": "使用补签券开放学期内历史日期的一次提交权限，提交记录后完成补签",
            "price": 3,
            "stock": -1,  # Unlimited
            "is_active": True
        }
    )


@transaction.atomic
def settle_weekly_streak(member, day):
    from .models import WeeklyStreakGrant, Submission
    if not member.team.currency_enabled:
        return 0
    TeamMembership.objects.select_for_update().get(pk=member.pk)
    monday = day - timedelta(days=day.weekday())
    dates = signed_dates(member,monday,monday+timedelta(days=6))
    longest = run = 0
    for offset in range(7):
        run = run + 1 if monday + timedelta(days=offset) in dates else 0
        longest = max(longest, run)
    awarded = 0
    for rule in StreakReward.objects.filter(team=member.team, days__lte=longest).order_by('days'):
        grant, created = WeeklyStreakGrant.objects.get_or_create(team=member.team,user_id=member.user_id, week_start=monday,
            days=rule.days, defaults={'member':member,'amount':rule.reward})
        if created:
            add_currency(member, rule.reward, CurrencyTransaction.STREAK_BONUS,
                f'{monday.isoformat()} 自然周 {rule.days} 天连签奖励')
            awarded += rule.reward
    return awarded
