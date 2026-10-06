from django.urls import path

from . import views

urlpatterns = [
    path("semesters", views.semesters),
    path("attachments/<int:part_id>", views.attachment),
    path("csrf", views.api_csrf),
    path("auth/join", views.join_team),
    path("auth/login", views.login_view),
    path("auth/register", views.register_account),
    path("auth/logout", views.logout_view),
    path("auth/create-team", views.create_team),
    path("team/select", views.select_team),
    path("me", views.me),
    path("dashboard", views.dashboard),
    path("members", views.members),
    path("members/<int:member_id>/history", views.member_history),
    path("submissions", views.submissions),
    path("showcase", views.showcase),
    path("leaderboard", views.leaderboard),
    path("admin/submissions/bulk-approve", views.bulk_approve),
    path("admin/team-settings", views.team_settings),
    path("arena", views.arena),
    path("admin/arena", views.arena_admin),
    path("export", views.export_xlsx),
]
