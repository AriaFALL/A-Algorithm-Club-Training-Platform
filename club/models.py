import uuid
from datetime import datetime, time, timedelta

from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class SolvedProblemCredit(models.Model):
    """Lifetime evidence, independent of semester, membership and transient sync rows."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='solved_credits')
    source = models.CharField(max_length=16)
    problem_key = models.CharField(max_length=1100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'source', 'problem_key'], name='unique_user_solved_credit')]


class ContestCalendarSnapshot(models.Model):
    platform = models.CharField(max_length=20, unique=True)
    contests = models.JSONField(default=list)
    updated_at = models.DateTimeField(null=True, blank=True)
    attempted_at = models.DateTimeField(null=True, blank=True)
    error = models.CharField(max_length=100, blank=True)


class ExtensionResource(models.Model):
    title = models.CharField(max_length=100)
    description = models.CharField(max_length=300, blank=True)
    url = models.URLField(max_length=2000, blank=True)
    upload = models.FileField(upload_to='extensions/files/', blank=True)
    filename = models.CharField(max_length=255, blank=True)
    cover = models.ImageField(upload_to='extensions/covers/', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']


class Team(models.Model):
    name = models.CharField(max_length=80)
    code = models.CharField(max_length=32, unique=True)
    cleanup_delay_days = models.PositiveIntegerField(default=30, validators=[MinValueValidator(1)])
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_teams")
    created_at = models.DateTimeField(auto_now_add=True)

    # Currency system configuration
    currency_enabled = models.BooleanField(default=False, verbose_name="启用货币系统")
    currency_icon = models.FileField(upload_to="currency_icons/", blank=True, verbose_name="货币图标")
    daily_checkin_reward = models.PositiveIntegerField(default=1, verbose_name="每日签到奖励")
    problem_rewards = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"{self.name} ({self.code})"


class TeamMembership(models.Model):
    MEMBER = "member"
    ADMIN = "admin"
    OWNER = ADMIN  # Compatibility for internal callers; no separate owner role.
    ROLE_CHOICES = [(MEMBER, "普通用户"), (ADMIN, "团队管理用户")]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="team_memberships")
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships")
    display_name = models.CharField(max_length=40)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=MEMBER)
    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "display_name"], name="unique_team_display_name"),
                       models.UniqueConstraint(fields=['team', 'user'], name='unique_team_user'),
                       models.CheckConstraint(condition=models.Q(role__in=['member', 'admin']), name='valid_membership_role')]
        ordering = ["display_name"]

    @property
    def is_admin(self):
        return self.role == self.ADMIN


class Semester(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="semesters")
    name = models.CharField(max_length=80)
    starts_on = models.DateField()
    ends_on = models.DateField()
    min_submissions = models.PositiveIntegerField(default=4)
    min_score = models.PositiveIntegerField(default=10)
    require_both = models.BooleanField(default=True)
    screenshot_points = models.PositiveIntegerField(default=1)
    logic_points = models.PositiveIntegerField(default=1)
    blog_points = models.PositiveIntegerField(default=1)
    cleanup_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    calendar_managed = models.BooleanField(default=False)

    class Meta:
        ordering = ["-starts_on"]



class Week(models.Model):
    semester = models.ForeignKey(Semester, on_delete=models.CASCADE, related_name="weeks")
    number = models.PositiveIntegerField()
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    min_submissions = models.PositiveIntegerField(null=True, blank=True)
    min_score = models.PositiveIntegerField(null=True, blank=True)
    require_both = models.BooleanField(null=True, blank=True)
    is_closed = models.BooleanField(default=False)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["semester", "number"], name="unique_semester_week")]
        ordering = ["semester", "number"]

    @property
    def effective_min_submissions(self):
        return self.min_submissions if self.min_submissions is not None else self.semester.min_submissions

    @property
    def effective_min_score(self):
        return self.min_score if self.min_score is not None else self.semester.min_score

    @property
    def effective_require_both(self):
        return self.require_both if self.require_both is not None else self.semester.require_both


class MakeupPermission(models.Model):
    member = models.ForeignKey(TeamMembership, on_delete=models.CASCADE, related_name='makeup_permissions')
    semester = models.ForeignKey(Semester, on_delete=models.CASCADE)
    record_date = models.DateField()
    opened_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['member', 'semester', 'record_date'], name='unique_makeup_permission')]


class Submission(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="submissions")
    member = models.ForeignKey(TeamMembership, on_delete=models.CASCADE, related_name="submissions")
    semester = models.ForeignKey(Semester, on_delete=models.CASCADE, related_name="submissions")
    week = models.ForeignKey(Week, on_delete=models.CASCADE, related_name="submissions")
    submitted_at = models.DateTimeField(auto_now_add=True)
    record_date = models.DateField(default=timezone.localdate)
    is_valid = models.BooleanField(default=True)
    cleaned_at = models.DateTimeField(null=True, blank=True)
    problem = models.ForeignKey('Problem', null=True, on_delete=models.PROTECT, related_name='submissions')
    version = models.PositiveIntegerField(default=1)
    rejection_note = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-submitted_at"]


class SubmissionPart(models.Model):
    PROOF = "proof"
    LOGIC = "logic"
    BLOG = "blog"
    KIND_CHOICES = [(PROOF, "通过截图"), (LOGIC, "写题逻辑"), (BLOG, "Blog")]
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    STATUS_CHOICES = [(PENDING, "待审核"), (APPROVED, "已通过"), (REJECTED, "已拒绝")]

    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="parts")
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    text_content = models.TextField(blank=True)
    link = models.URLField(blank=True)
    upload = models.FileField(upload_to="submissions/%Y/%m/", blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    points_awarded = models.PositiveIntegerField(default=0)
    review_note = models.CharField(max_length=500, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_parts")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["submission", "kind"], name="unique_submission_part")]

    @property
    def has_content(self):
        return bool(self.text_content or self.link or self.upload)


class ReviewLog(models.Model):
    submission = models.ForeignKey(Submission, null=True, blank=True, on_delete=models.SET_NULL, related_name="review_logs")
    part = models.ForeignKey(SubmissionPart, null=True, blank=True, on_delete=models.SET_NULL, related_name="review_logs")
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=40)
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class SemesterMemberTotal(models.Model):
    semester = models.ForeignKey(Semester, on_delete=models.CASCADE, related_name="member_totals")
    member = models.ForeignKey(TeamMembership, on_delete=models.CASCADE, related_name="semester_totals")
    total_score = models.PositiveIntegerField(default=0)
    qualified_weeks = models.PositiveIntegerField(default=0)
    total_submissions = models.PositiveIntegerField(default=0)
    display_name = models.CharField(max_length=40, blank=True)
    finalized_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["semester", "member"], name="unique_semester_member_total")]


class CleanupJob(models.Model):
    semester = models.OneToOneField(Semester, on_delete=models.CASCADE, related_name="cleanup_job")
    scheduled_for = models.DateTimeField()
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, default="scheduled")
    deleted_submissions = models.PositiveIntegerField(default=0)
    deleted_files = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)
    pending_files = models.JSONField(default=list, blank=True)


class Problem(models.Model):
    identity = models.CharField(max_length=1100, unique=True)
    url = models.URLField(max_length=1000)
    title = models.CharField(max_length=200, blank=True)
    status = models.CharField('解析状态', max_length=16, default='pending', choices=[('pending', '待解析'), ('running', '解析中'), ('success', '成功'), ('failed', '待处理'), ('manual', '人工补填'), ('cancelled', '任务已移除')])
    mode = models.CharField(max_length=10, default='smart')
    generation = models.PositiveIntegerField(default=0)
    error = models.CharField(max_length=500, blank=True)
    requested_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = '题目与题名待处理'
        verbose_name_plural = '题目与题名待处理'

    def __str__(self):
        return self.title or self.url


class ParserSettings(models.Model):
    encrypted_luogu_cookie = models.TextField(blank=True)
    MODES = [('auto', '自动解析'), ('ai', 'AI解析'), ('smart', '智能解析')]
    mode = models.CharField(max_length=10, choices=MODES, default='smart')
    enabled = models.BooleanField(default=True)
    api_protocol = models.CharField('调用协议', max_length=16, default='chat', choices=[('chat', 'Chat Completions'), ('responses', 'Responses 联网')])
    base_url = models.URLField(max_length=500, blank=True)
    model = models.CharField(max_length=200, blank=True)
    encrypted_key = models.TextField(blank=True)

    class Meta:
        verbose_name = '全站题名解析配置'
        verbose_name_plural = '全站题名解析配置'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def __str__(self):
        return '全站题名解析配置'


class SubmissionLike(models.Model):
    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name='likes')
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['submission', 'user'], name='unique_submission_like')]


class SubmissionReport(models.Model):
    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name='reports')
    version = models.PositiveIntegerField()
    reporter = models.ForeignKey(User, on_delete=models.CASCADE)
    status = models.CharField(max_length=12, default='pending', choices=[('pending', '待处理'), ('dismissed', '已驳回'), ('rejected', '已退回')])
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='resolved_reports')
    note = models.CharField(max_length=500, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['submission', 'version', 'reporter'], name='unique_submission_report')]


class FileDeletion(models.Model):
    name = models.CharField(max_length=1000)
    error = models.CharField(max_length=500, blank=True)

    class Meta:
        verbose_name = '待删除文件清单'
        verbose_name_plural = '待删除文件清单'


def create_internal_username(team_code, display_name):
    return f"{team_code}-{uuid.uuid4().hex[:12]}"


# Currency system models
class CurrencyBalance(models.Model):
    """User currency balance for a team"""
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="currency_balances")
    member = models.ForeignKey(TeamMembership, on_delete=models.CASCADE, related_name="currency_balance")
    balance = models.IntegerField(default=0, verbose_name="当前余额")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "member"], name="unique_team_member_balance")
        ]
        verbose_name = "货币余额"
        verbose_name_plural = "货币余额"

    def __str__(self):
        return f"{self.member.display_name} - {self.balance} RBC"


class CurrencyTransaction(models.Model):
    """Currency transaction history"""
    CHECKIN = "checkin"
    STREAK_BONUS = "streak_bonus"
    CONTEST_REWARD = "contest_reward"
    PURCHASE = "purchase"
    ADMIN_ADJUST = "admin_adjust"

    TYPE_CHOICES = [
        (CHECKIN, "每日签到"),
        (STREAK_BONUS, "连签奖励"),
        (CONTEST_REWARD, "比赛过题奖励"),
        (PURCHASE, "商店购买"),
        (ADMIN_ADJUST, "管理员调整"),
        ("tip_sent", "打赏支出"),
        ("tip_received", "收到打赏"),
    ]

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="currency_transactions")
    member = models.ForeignKey(TeamMembership, on_delete=models.CASCADE, related_name="currency_transactions")
    amount = models.IntegerField(verbose_name="变动金额")
    balance_after = models.IntegerField(verbose_name="变动后余额")
    transaction_type = models.CharField(max_length=20, choices=TYPE_CHOICES, verbose_name="交易类型")
    description = models.CharField(max_length=200, blank=True, verbose_name="描述")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="currency_transactions")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "货币交易记录"
        verbose_name_plural = "货币交易记录"

    def __str__(self):
        return f"{self.member.display_name} {self.amount:+d} ({self.get_transaction_type_display()})"


class CheckinRecord(models.Model):
    """Daily check-in records"""
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="checkin_records")
    member = models.ForeignKey(TeamMembership, on_delete=models.CASCADE, related_name="checkin_records")
    checkin_date = models.DateField(verbose_name="签到日期")
    is_makeup = models.BooleanField(default=False, verbose_name="是否补签")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "member", "checkin_date"], name="unique_team_member_checkin_date")
        ]
        ordering = ["-checkin_date"]
        verbose_name = "签到记录"
        verbose_name_plural = "签到记录"

    def __str__(self):
        return f"{self.member.display_name} - {self.checkin_date}"


class StreakReward(models.Model):
    """Streak reward configuration for teams"""
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="streak_rewards")
    days = models.PositiveIntegerField(validators=[MinValueValidator(1)], verbose_name="连签天数")
    reward = models.PositiveIntegerField(validators=[MinValueValidator(1)], verbose_name="奖励金额")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "days"], name="unique_team_streak_days")
        ]
        ordering = ["days"]
        verbose_name = "连签奖励配置"
        verbose_name_plural = "连签奖励配置"

    def __str__(self):
        return f"{self.team.name} - {self.days}天 +{self.reward}"


class ContestRewardConfig(models.Model):
    """Contest problem-solving reward configuration"""
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="contest_reward_configs")
    problems_solved = models.PositiveIntegerField(validators=[MinValueValidator(1)], verbose_name="过题数量")
    reward = models.PositiveIntegerField(validators=[MinValueValidator(1)], verbose_name="奖励金额")
    is_ak = models.BooleanField(default=False, verbose_name="是否为AK奖励")

    class Meta:
        ordering = ["problems_solved"]
        verbose_name = "比赛奖励配置"
        verbose_name_plural = "比赛奖励配置"

    def __str__(self):
        if self.is_ak:
            return f"{self.team.name} - AK +{self.reward}"
        return f"{self.team.name} - {self.problems_solved}题 +{self.reward}"


class ContestSubmission(models.Model):
    """Contest problem-solving submission records"""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

    STATUS_CHOICES = [
        (PENDING, "待审核"),
        (APPROVED, "已通过"),
        (REJECTED, "已拒绝"),
    ]

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="contest_submissions")
    member = models.ForeignKey(TeamMembership, on_delete=models.CASCADE, related_name="contest_submissions")
    contest_name = models.CharField(max_length=200, verbose_name="比赛名称")
    contest_url = models.URLField(max_length=500, blank=True, verbose_name="比赛链接")
    screenshot = models.ImageField(upload_to="contest_submissions/%Y/%m/", verbose_name="过题截图")
    problems_solved = models.PositiveIntegerField(default=0, verbose_name="过题数量")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING, verbose_name="审核状态")
    reward_amount = models.PositiveIntegerField(default=0, verbose_name="奖励金额")
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_contest_submissions")
    review_note = models.CharField(max_length=500, blank=True, verbose_name="审核备注")

    class Meta:
        ordering = ["-submitted_at"]
        verbose_name = "比赛提交记录"
        verbose_name_plural = "比赛提交记录"

    def __str__(self):
        return f"{self.member.display_name} - {self.contest_name} ({self.problems_solved}题)"


class ShopItem(models.Model):
    """RBC Shop items"""
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="shop_items")
    name = models.CharField(max_length=100, verbose_name="商品名称")
    description = models.TextField(blank=True, verbose_name="商品描述")
    icon = models.ImageField(upload_to="shop_items/", blank=True, verbose_name="商品图标")
    price = models.PositiveIntegerField(validators=[MinValueValidator(1)], verbose_name="价格")
    stock = models.IntegerField(default=-1, verbose_name="库存")
    is_active = models.BooleanField(default=True, verbose_name="是否上架")
    item_type = models.CharField(max_length=50, default="general", verbose_name="商品类型")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["price", "name"]
        verbose_name = "商店商品"
        verbose_name_plural = "商店商品"

    def __str__(self):
        return f"{self.name} - {self.price} RBC"


class Purchase(models.Model):
    """Purchase history"""
    request_id = models.UUIDField(null=True,unique=True)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="purchases")
    member = models.ForeignKey(TeamMembership, on_delete=models.CASCADE, related_name="purchases")
    item = models.ForeignKey(ShopItem, on_delete=models.PROTECT, related_name="purchases")
    quantity = models.PositiveIntegerField(default=1, verbose_name="数量")
    total_price = models.PositiveIntegerField(verbose_name="总价")
    purchased_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-purchased_at"]
        verbose_name = "购买记录"
        verbose_name_plural = "购买记录"

    def __str__(self):
        return f"{self.member.display_name} - {self.item.name} x{self.quantity}"


class UserInventory(models.Model):
    """User inventory for consumable items"""
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="user_inventories")
    member = models.ForeignKey(TeamMembership, on_delete=models.CASCADE, related_name="inventory")
    item = models.ForeignKey(ShopItem, on_delete=models.PROTECT, related_name="user_inventories")
    quantity = models.PositiveIntegerField(default=0, verbose_name="数量")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "member", "item"], name="unique_team_member_item")
        ]
        verbose_name = "用户库存"
        verbose_name_plural = "用户库存"

    def __str__(self):
        return f"{self.member.display_name} - {self.item.name} x{self.quantity}"


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='personal_profile')
    avatar = models.ImageField(upload_to='avatars/', blank=True)
    grade = models.PositiveSmallIntegerField(null=True, blank=True)
    grade_date = models.DateField(null=True, blank=True)


class PlatformBinding(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='platform_bindings')
    platform = models.CharField(max_length=20)
    account = models.CharField(max_length=100)
    snapshot = models.JSONField(default=dict)
    status = models.CharField(max_length=16, default='pending')
    error = models.CharField(max_length=240, blank=True)
    sync_token = models.UUIDField(default=uuid.uuid4)
    requested_at = models.DateTimeField(default=timezone.now)
    synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'platform'], name='unique_user_platform')]


def default_problem_rewards():
    return {'beginner': [1, 2, 3], 'experienced': [1, 2, 3]}


class WeeklyStreakGrant(models.Model):
    member = models.ForeignKey(TeamMembership, null=True, on_delete=models.SET_NULL)
    user = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    week_start = models.DateField()
    days = models.PositiveSmallIntegerField()
    amount = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['member', 'week_start', 'days'], name='unique_weekly_streak_grant'),
                       models.UniqueConstraint(fields=['team','user','week_start','days'], name='unique_user_team_weekly_grant')]


class ContestSyncState(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    token = models.UUIDField(default=uuid.uuid4)
    status = models.CharField(max_length=16, default='idle')
    progressed_at = models.DateTimeField(null=True)
    requested_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)
    messages = models.JSONField(default=dict)
    remaining = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)


class ContestParticipation(models.Model):
    hydrated_token = models.UUIDField(null=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='contest_participations')
    platform = models.CharField(max_length=20)
    account = models.CharField(max_length=100)
    contest_key = models.CharField(max_length=100)
    title = models.CharField(max_length=300)
    url = models.URLField(max_length=500)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    verified_at = models.DateTimeField(auto_now=True)
    source_data = models.JSONField(default=dict)
    sync_error = models.CharField(max_length=240, blank=True)
    detail_complete = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'platform', 'account', 'contest_key'], name='unique_contest_participation')]


class ContestProblemProgress(models.Model):
    participation = models.ForeignKey(ContestParticipation, on_delete=models.CASCADE, related_name='problems')
    problem_key = models.CharField(max_length=100)
    label = models.CharField(max_length=30)
    title = models.CharField(max_length=300)
    url = models.URLField(max_length=500)
    difficulty = models.FloatField(null=True)
    difficulty_source = models.CharField(max_length=100, blank=True)
    accepted = models.BooleanField(default=False)
    official_ac = models.BooleanField(default=False)
    accepted_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['participation', 'problem_key'], name='unique_participation_problem')]


class ContestProblemClaim(models.Model):
    member = models.ForeignKey(TeamMembership, null=True, on_delete=models.SET_NULL)
    user = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    platform = models.CharField(max_length=20)
    account = models.CharField(max_length=100)
    contest_key = models.CharField(max_length=100)
    problem_key = models.CharField(max_length=100)
    amount = models.PositiveIntegerField()
    group = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['team', 'user', 'platform', 'contest_key', 'problem_key'], name='unique_user_team_problem_claim'),
            models.UniqueConstraint(fields=['member', 'platform', 'contest_key', 'problem_key'], name='unique_member_problem_claim'),
            models.UniqueConstraint(fields=['team', 'platform', 'account', 'contest_key', 'problem_key'], name='unique_team_account_problem_claim'),
        ]


class SubmissionTip(models.Model):
    request_id = models.UUIDField(unique=True)
    team = models.ForeignKey(Team,on_delete=models.CASCADE)
    sender_user = models.ForeignKey(User,null=True,on_delete=models.SET_NULL)
    sender = models.ForeignKey(TeamMembership,null=True,on_delete=models.SET_NULL,related_name='tips_sent')
    recipient = models.ForeignKey(TeamMembership,null=True,on_delete=models.SET_NULL,related_name='tips_received')
    submission = models.ForeignKey(Submission,null=True,on_delete=models.SET_NULL)
    amount = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
