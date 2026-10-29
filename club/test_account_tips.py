import json
import uuid
from unittest.mock import patch
from django.test import TestCase,Client
from . import test_community as fixtures
from .models import TeamMembership,CurrencyBalance,CurrencyTransaction,SubmissionTip,Submission


class TipTests(TestCase):
    image=fixtures.CommunityTests.image
    post=fixtures.CommunityTests.post
    submit=fixtures.CommunityTests.submit

    def setUp(self):
        fixtures.CommunityTests.setUp(self)
        self.submit()
        self.team.currency_enabled=True;self.team.save()
        self.target=Submission.objects.get(member=self.author_member)
        self.sender=TeamMembership.objects.get(user=self.reader,team=self.team)
        CurrencyBalance.objects.create(team=self.team,member=self.sender,balance=20)
        self.client.force_login(self.reader)

    def tip(self,amount=7,token=None):
        return self.post(f'/api/submissions/{self.target.pk}/tip',{'amount':amount,'request_id':str(token or uuid.uuid4())})

    def test_transfer_exactly_once_and_balanced_ledger(self):
        token=uuid.uuid4()
        self.assertEqual(self.tip(token=token).status_code,200)
        self.assertEqual(self.tip(token=token).status_code,200)
        self.assertEqual(CurrencyBalance.objects.get(member=self.sender).balance,13)
        self.assertEqual(CurrencyBalance.objects.get(member=self.author_member).balance,7)
        self.assertEqual(SubmissionTip.objects.count(),1)
        self.assertEqual(sorted(CurrencyTransaction.objects.values_list('amount',flat=True)),[-7,7])
        self.assertEqual(self.tip(amount=8,token=token).status_code,409)

    def test_invalid_insufficient_self_and_cross_team(self):
        for amount in [0,-1,1.5,True,'2',21]:
            self.assertEqual(self.tip(amount).status_code,400)
        self.client.force_login(self.author)
        self.assertEqual(self.tip().status_code,403)
        self.client.force_login(self.reader)
        from .models import Team
        other=Team.objects.create(name='Elsewhere',code='TIP-OTHER',created_by=self.owner)
        TeamMembership.objects.create(team=other,user=self.reader,display_name='Other member')
        session=self.client.session;session['team_id']=other.pk;session.save()
        self.assertEqual(self.tip().status_code,404)
        session=self.client.session;session['team_id']=self.team.pk;session.save()
        self.target.is_valid=False;self.target.save()
        self.assertEqual(self.tip().status_code,409)
        self.assertEqual(SubmissionTip.objects.count(),0)
        self.assertEqual(CurrencyBalance.objects.get(member=self.sender).balance,20)

    def test_credit_failure_rolls_back_debit_receipt_and_ledger(self):
        with patch('club.currency_services.add_currency',side_effect=RuntimeError('credit failure')):
            with self.assertRaises(RuntimeError):self.tip()
        self.assertEqual(CurrencyBalance.objects.get(member=self.sender).balance,20)
        self.assertFalse(SubmissionTip.objects.exists())
        self.assertFalse(CurrencyTransaction.objects.exists())


class PasswordTests(TestCase):
    def test_password_validation_and_other_session_invalidation(self):
        from django.contrib.auth.models import User
        user=User.objects.create_user('password-qa',password='Current-Password-12')
        self.client.force_login(user);other=Client();other.force_login(user)
        url='/api/profile/password'
        def change(old,new='New-Password-345',confirm='New-Password-345'):
            return self.client.post(url,json.dumps({'old_password':old,'new_password':new,'confirm_password':confirm}),content_type='application/json')
        self.assertEqual(change('wrong').status_code,400)
        self.assertEqual(change('Current-Password-12',confirm='different').status_code,400)
        self.assertEqual(change('Current-Password-12').status_code,200)
        user.refresh_from_db();self.assertTrue(user.check_password('New-Password-345'))
        self.assertFalse(user.check_password('Current-Password-12'))
        self.assertEqual(str(self.client.session['_auth_user_id']),str(user.pk))
        other.get('/api/me');self.assertNotIn('_auth_user_id',other.session)
