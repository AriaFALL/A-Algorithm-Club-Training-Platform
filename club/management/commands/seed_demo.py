from datetime import date

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.contrib.auth.hashers import make_password

from club.models import Semester, Team, TeamMembership, create_internal_username
from club.services import build_weeks


class Command(BaseCommand):
    help = "Create a development team, administrator, and active semester."

    def add_arguments(self, parser):
        parser.add_argument("--team-code", default="ACM2026")
        parser.add_argument("--team-name", default="ACM 校队")
        parser.add_argument("--join-password", default="join-me-2026")
        parser.add_argument("--admin-invite", default="admin-me-2026")
        parser.add_argument("--member-password", default="member-2026")

    def handle(self, *args, **options):
        team_code = options["team_code"]
        owner, _ = User.objects.get_or_create(username="seed-owner")
        owner.set_password(options["member_password"])
        owner.save(update_fields=["password"])
        team, created = Team.objects.get_or_create(code=team_code, defaults={"name": options["team_name"], "join_password_hash": "", "created_by": owner})
        team.created_by = owner
        team.join_password_hash = make_password(options["join_password"])
        team.admin_invite_hash = make_password(options["admin_invite"])
        team.save()
        membership, _ = TeamMembership.objects.get_or_create(user=owner, team=team, defaults={"display_name": "林同学", "role": TeamMembership.OWNER})
        Semester.objects.filter(team=team, is_active=True).update(is_active=False)
        semester, _ = Semester.objects.get_or_create(team=team, name="2026 秋季学期", defaults={"starts_on": date(2026, 8, 30), "ends_on": date(2027, 1, 16)})
        semester.is_active = True
        semester.save()
        build_weeks(semester)
        self.stdout.write(self.style.SUCCESS(f"Team {team.code} ready. Login: {membership.display_name} / {options['member_password']}"))
