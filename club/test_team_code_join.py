import json

from django.contrib.auth.models import User
from django.test import TestCase

from .models import Team, TeamMembership


class TeamCodeJoinTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='new-learner', password='password-123')
        self.team = Team.objects.create(name='Training', code='JOIN2026', created_by=self.user)
        self.client.force_login(self.user)

    def join(self, payload):
        return self.client.post('/api/auth/join', json.dumps(payload), content_type='application/json')

    def test_code_only_join_uses_account_name_and_member_role(self):
        response = self.join({'team_code':'join2026', 'role':'admin'})
        self.assertEqual(response.status_code, 200, response.content)
        member = TeamMembership.objects.get(user=self.user, team=self.team)
        self.assertEqual((member.display_name, member.role), ('new-learner', 'member'))
        self.assertEqual(self.client.session['team_id'], self.team.pk)

    def test_existing_nickname_is_reused_in_another_team(self):
        other = Team.objects.create(name='Other', code='OTHER', created_by=self.user)
        TeamMembership.objects.create(user=self.user, team=other, display_name='已有昵称')
        self.assertEqual(self.join({'team_code':self.team.code}).status_code, 200)
        self.assertEqual(TeamMembership.objects.get(user=self.user, team=self.team).display_name, '已有昵称')

    def test_duplicate_default_nickname_is_disambiguated(self):
        other = User.objects.create_user(username='another')
        TeamMembership.objects.create(user=other, team=self.team, display_name=self.user.username)
        self.assertEqual(self.join({'team_code':self.team.code}).status_code, 200)
        self.assertEqual(TeamMembership.objects.get(user=self.user).display_name, 'new-learner-2')

    def test_invalid_code_does_not_create_membership(self):
        self.assertEqual(self.join({'team_code':'MISSING'}).status_code, 404)
        self.assertFalse(TeamMembership.objects.filter(user=self.user).exists())

    def test_repeated_join_does_not_create_duplicate_membership(self):
        self.assertEqual(self.join({'team_code':self.team.code}).status_code, 200)
        self.assertEqual(self.join({'team_code':self.team.code}).status_code, 400)
        self.assertEqual(TeamMembership.objects.filter(user=self.user).count(), 1)

    def test_team_model_has_no_join_password_column(self):
        self.assertNotIn('join_password_hash', [field.name for field in Team._meta.fields])
