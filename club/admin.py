from django.contrib import admin

from .models import CleanupJob, ReviewLog, Semester, SemesterMemberTotal, Submission, SubmissionPart, Team, TeamMembership, Week


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "visibility_mode", "cleanup_delay_days", "created_at")
    search_fields = ("name", "code")


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
