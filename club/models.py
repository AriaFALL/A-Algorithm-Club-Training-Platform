import uuid
from datetime import datetime, time, timedelta

from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class Team(models.Model):
    name = models.CharField(max_length=80)
    code = models.CharField(max_length=32, unique=True)
    join_password_hash = models.CharField(max_length=128)
    cleanup_delay_days = models.PositiveIntegerField(default=30, validators=[MinValueValidator(1)])
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_teams")
    created_at = models.DateTimeField(auto_now_add=True)

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
