from django.contrib import admin
from django import forms
from django.db.models import F, Count
from django.utils import timezone

from .models import CleanupJob, ReviewLog, Semester, SemesterMemberTotal, Submission, SubmissionPart, Team, TeamMembership, Week
from .models import ParserSettings, Problem, SubmissionReport, FileDeletion
from .problem_parser import key_cipher, enqueue_problem, ai_title
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

admin.site.site_header = '算法社团 · 站点管理'
admin.site.site_title = '算法社团管理后台'


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    exclude = ("cleanup_delay_days",)
    list_display = ("name", "code", "created_at")
    search_fields = ("name", "code")
    readonly_fields = ('created_by',)

    def has_add_permission(self, request):
        return False  # Creation through the workbench also creates the semester/weeks.

    def delete_model(self, request, obj):
        from .management_views import delete_team_data
        delete_team_data(obj)

    def delete_queryset(self, request, queryset):
        from .management_views import delete_team_data
        for team in queryset:
            delete_team_data(team)


@admin.register(TeamMembership)
class TeamMembershipAdmin(admin.ModelAdmin):
    list_display = ("display_name", "team", "role", "is_active", "joined_at")
    list_filter = ("team", "role", "is_active")
    search_fields = ("display_name", "team__name")


@admin.register(Semester)
class SemesterAdmin(admin.ModelAdmin):
    list_display = ("name", "team", "starts_on", "ends_on", "is_active", "cleanup_at")
    list_filter = ("team", "is_active")


@admin.register(Week)
class WeekAdmin(admin.ModelAdmin):
    list_display = ("semester", "number", "starts_at", "ends_at", "is_closed")
    list_filter = ("semester", "is_closed")


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ("member", "week", "submitted_at", "is_valid")
    list_filter = ("team", "semester", "is_valid")
    search_fields = ("member__display_name",)


@admin.register(SubmissionPart)
class SubmissionPartAdmin(admin.ModelAdmin):
    list_display = ("submission", "kind", "status", "points_awarded", "reviewed_at")
    list_filter = ("kind", "status")


admin.site.register(ReviewLog)
admin.site.register(SemesterMemberTotal)
admin.site.register(CleanupJob)

admin.site.unregister(User)


@admin.register(User)
class PlatformUserAdmin(UserAdmin):
    def get_readonly_fields(self, request, obj=None):
        fields = ('is_staff', 'is_superuser', 'groups', 'user_permissions')
        return fields + ('username', 'is_active') if obj and obj.is_superuser else fields

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser and not (obj and obj.is_superuser)

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop('delete_selected', None)
        return actions


class SuperuserOnly:
    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return False


class ParserSettingsForm(forms.ModelForm):
    api_key = forms.CharField(label='API Key', required=False, widget=forms.PasswordInput(render_value=False), help_text='已保存时显示为掩码；留空保留原Key。')

    class Meta:
        model = ParserSettings
        fields = ['mode', 'enabled', 'api_protocol', 'base_url', 'model', 'api_key']
        labels = {'mode': '解析模式', 'enabled': '启用AI调用', 'base_url': 'API Base URL（含 /v1）', 'model': 'Model'}


@admin.register(ParserSettings)
class ParserSettingsAdmin(SuperuserOnly, admin.ModelAdmin):
    form = ParserSettingsForm
    list_display = ('__str__', 'mode', 'enabled', 'model')
    readonly_fields = ('key_status',)
    actions = ['test_connection']

    @admin.display(description='已保存的API Key')
    def key_status(self, obj):
        return '••••••••（已保存）' if obj and obj.encrypted_key else '未配置'

    def has_add_permission(self, request):
        return request.user.is_superuser and not ParserSettings.objects.exists()

    def save_model(self, request, obj, form, change):
        if form.cleaned_data.get('api_key'):
            obj.encrypted_key = key_cipher().encrypt(form.cleaned_data['api_key'].encode()).decode()
        super().save_model(request, obj, form, change)

    @admin.action(description='测试AI连接（使用牛客示例题目）')
    def test_connection(self, request, queryset):
        for config in queryset:
            try:
                title = ai_title('https://www.nowcoder.com/practice/d53b2057ae8a4eaf8155447f6b709361', config)
                self.message_user(request, '连接及响应验证成功，题名：' + title)
            except ValueError as exc:
                self.message_user(request, str(exc), level='ERROR')


@admin.register(Problem)
class ProblemAdmin(SuperuserOnly, admin.ModelAdmin):
    list_display = ('__str__', 'url', 'status', 'mode', 'error', 'requested_at', 'references')
    list_filter = ('status', 'mode')
    search_fields = ('title', 'url')
    fields = ('title', 'url', 'status', 'mode', 'error', 'requested_at', 'references')
    readonly_fields = ('url', 'status', 'mode', 'error', 'requested_at', 'references')
    actions = ['retry_auto', 'retry_ai', 'retry_smart']

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if 'title' in form.base_fields:
            form.base_fields['title'].label = '题目名称（可人工补填）'
        return form

    def has_add_permission(self, request):
        return False

    @admin.display(description='引用数量')
    def references(self, obj):
        return obj.submissions.count()

    def save_model(self, request, obj, form, change):
        if 'title' in form.changed_data:
            # Admin form constrains length; manual names need not match parser heuristics.
            Problem.objects.filter(pk=obj.pk).update(title=obj.title.strip(), generation=F('generation') + 1,
                status='manual' if obj.title.strip() else 'failed', error='' if obj.title.strip() else '题名待补填')

    def retry(self, request, queryset, mode):
        for problem in queryset:
            enqueue_problem(problem, mode)
        self.message_user(request, '已按所选模式加入解析队列')

    @admin.action(description='重新解析：自动解析')
    def retry_auto(self, request, queryset):
        self.retry(request, queryset, 'auto')

    @admin.action(description='重新解析：AI解析')
    def retry_ai(self, request, queryset):
        self.retry(request, queryset, 'ai')

    @admin.action(description='重新解析：智能解析')
    def retry_smart(self, request, queryset):
        self.retry(request, queryset, 'smart')


@admin.register(FileDeletion)
class FileDeletionAdmin(SuperuserOnly, admin.ModelAdmin):
    list_display = ('name', 'error')
    readonly_fields = ('name', 'error')

    def has_add_permission(self, request):
        return False
