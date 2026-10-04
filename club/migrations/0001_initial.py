# Generated manually for the initial deployment.
import django.db.models.deletion
import django.db.models.manager
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name="Team",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=80)),
                ("code", models.CharField(max_length=32, unique=True)),
                ("join_password_hash", models.CharField(max_length=128)),
                ("visibility_mode", models.CharField(choices=[("team", "团队成员可见"), ("admin", "仅管理员可见")], default="team", max_length=10)),
                ("cleanup_delay_days", models.PositiveIntegerField(default=30)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_teams", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="TeamMembership",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("display_name", models.CharField(max_length=40)),
                ("role", models.CharField(choices=[("member", "成员"), ("admin", "管理员"), ("owner", "创建者")], default="member", max_length=10)),
                ("is_active", models.BooleanField(default=True)),
                ("joined_at", models.DateTimeField(auto_now_add=True)),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="memberships", to="club.team")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="team_memberships", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["display_name"]},
        ),
        migrations.CreateModel(
            name="Semester",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=80)),
                ("starts_on", models.DateField()),
                ("ends_on", models.DateField()),
                ("min_submissions", models.PositiveIntegerField(default=4)),
                ("min_score", models.PositiveIntegerField(default=10)),
                ("require_both", models.BooleanField(default=True)),
                ("screenshot_points", models.PositiveIntegerField(default=1)),
                ("logic_points", models.PositiveIntegerField(default=1)),
                ("blog_points", models.PositiveIntegerField(default=1)),
                ("cleanup_at", models.DateTimeField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="semesters", to="club.team")),
            ],
            options={"ordering": ["-starts_on"]},
        ),
        migrations.CreateModel(
            name="Week",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("number", models.PositiveIntegerField()),
                ("starts_at", models.DateTimeField()),
                ("ends_at", models.DateTimeField()),
                ("min_submissions", models.PositiveIntegerField(blank=True, null=True)),
                ("min_score", models.PositiveIntegerField(blank=True, null=True)),
                ("require_both", models.BooleanField(blank=True, null=True)),
                ("is_closed", models.BooleanField(default=False)),
                ("settled_at", models.DateTimeField(blank=True, null=True)),
                ("semester", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="weeks", to="club.semester")),
            ],
            options={"ordering": ["semester", "number"]},
        ),
        migrations.CreateModel(
            name="Submission",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("submitted_at", models.DateTimeField(auto_now_add=True)),
                ("is_valid", models.BooleanField(default=True)),
                ("cleaned_at", models.DateTimeField(blank=True, null=True)),
                ("member", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="submissions", to="club.teammembership")),
                ("semester", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="submissions", to="club.semester")),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="submissions", to="club.team")),
                ("week", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="submissions", to="club.week")),
            ],
            options={"ordering": ["-submitted_at"]},
        ),
        migrations.CreateModel(
            name="SubmissionPart",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("proof", "通过截图"), ("logic", "写题逻辑"), ("blog", "Blog")], max_length=10)),
                ("text_content", models.TextField(blank=True)),
                ("link", models.URLField(blank=True)),
                ("upload", models.FileField(blank=True, upload_to="submissions/%Y/%m/")),
                ("status", models.CharField(choices=[("pending", "待审核"), ("approved", "已通过"), ("rejected", "已拒绝")], default="pending", max_length=10)),
                ("points_awarded", models.PositiveIntegerField(default=0)),
                ("review_note", models.CharField(blank=True, max_length=500)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reviewed_parts", to=settings.AUTH_USER_MODEL)),
                ("submission", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="parts", to="club.submission")),
            ],
        ),
        migrations.CreateModel(
            name="ReviewLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(max_length=40)),
                ("detail", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ("part", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="review_logs", to="club.submissionpart")),
                ("submission", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="review_logs", to="club.submission")),
            ],
        ),
        migrations.CreateModel(
            name="SemesterMemberTotal",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("total_score", models.PositiveIntegerField(default=0)),
                ("qualified_weeks", models.PositiveIntegerField(default=0)),
                ("total_submissions", models.PositiveIntegerField(default=0)),
                ("finalized_at", models.DateTimeField(auto_now=True)),
                ("member", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="semester_totals", to="club.teammembership")),
                ("semester", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="member_totals", to="club.semester")),
            ],
        ),
        migrations.CreateModel(
            name="CleanupJob",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("scheduled_for", models.DateTimeField()),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("status", models.CharField(default="scheduled", max_length=20)),
                ("deleted_submissions", models.PositiveIntegerField(default=0)),
                ("deleted_files", models.PositiveIntegerField(default=0)),
                ("error", models.TextField(blank=True)),
                ("semester", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="cleanup_job", to="club.semester")),
            ],
        ),
        migrations.AddConstraint(model_name="teammembership", constraint=models.UniqueConstraint(fields=("team", "display_name"), name="unique_team_display_name")),
        migrations.AddConstraint(model_name="week", constraint=models.UniqueConstraint(fields=("semester", "number"), name="unique_semester_week")),
        migrations.AddConstraint(model_name="submissionpart", constraint=models.UniqueConstraint(fields=("submission", "kind"), name="unique_submission_part")),
        migrations.AddConstraint(model_name="semestermembertotal", constraint=models.UniqueConstraint(fields=("semester", "member"), name="unique_semester_member_total")),
    ]
