from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone
from . import test_community as fixtures
from .currency_services import makeup_checkin
from .models import (CheckinRecord, ShopItem, UserInventory, Submission, MakeupPermission,
                     StreakReward, WeeklyStreakGrant)


class DailyRecordsTests(TestCase):
    image = fixtures.CommunityTests.image

    def setUp(self):
        fixtures.CommunityTests.setUp(self)
        self.team.currency_enabled = True
        self.team.save(update_fields=['currency_enabled'])
        self.ticket = ShopItem.objects.create(team=self.team, name='补签券', item_type='makeup_ticket', price=3)
        self.inventory = UserInventory.objects.create(team=self.team, member=self.author_member, item=self.ticket, quantity=3)
        self.day = timezone.localdate() - timedelta(days=1)

    def makeup(self, day):
        import json
        return self.client.post('/api/currency/checkin/makeup', json.dumps({'checkin_date': day}), content_type='application/json')

    def submit(self, day, **extra):
        week = self.semester.weeks.get(starts_at__date__lte=day, ends_at__date__gt=day)
        payload = {'week_id': week.pk, 'problem_url':fixtures.URL,
                   'record_date':day.isoformat(), 'proof':self.image(), **extra}
        with patch('club.problem_parser.get_problem', return_value=self.problem):
            return self.client.post('/api/submissions', payload)

    def test_opening_only_spends_ticket_and_retry_is_idempotent(self):
        first = self.makeup(self.day.isoformat())
        self.assertEqual(first.status_code,200,first.content)
        self.assertFalse(first.json()['completed'])
        self.assertFalse(first.json()['already_open'])
        self.inventory.refresh_from_db(); self.assertEqual(self.inventory.quantity,2)
        self.assertFalse(CheckinRecord.objects.filter(member=self.author_member).exists())
        self.assertFalse(Submission.objects.filter(member=self.author_member).exists())
        self.assertIsNone(MakeupPermission.objects.get(member=self.author_member).completed_at)
        self.inventory.quantity=0; self.inventory.save()
        self.assertTrue(self.makeup(self.day.isoformat()).json()['already_open'])
        self.inventory.refresh_from_db(); self.assertEqual(self.inventory.quantity,0)
        dashboard=self.client.get('/api/dashboard').json()
        day=next(d for d in dashboard['pulse'] if d['date']==self.day.isoformat())
        self.assertTrue(day['makeupOpen']); self.assertFalse(day['submitted']); self.assertFalse(day['isMakeup'])
        self.assertEqual(dashboard['streakDays'],0)

    def test_submission_completes_permission_and_cannot_be_repeated(self):
        self.makeup(self.day.isoformat())
        response=self.submit(self.day)
        self.assertEqual(response.status_code,201,response.content)
        record=CheckinRecord.objects.get(member=self.author_member,checkin_date=self.day)
        self.assertTrue(record.is_makeup)
        self.assertIsNotNone(MakeupPermission.objects.get(member=self.author_member).completed_at)
        self.assertEqual(self.submit(self.day).status_code,409)
        self.assertEqual(self.makeup(self.day.isoformat()).status_code,400)
        self.inventory.refresh_from_db();self.assertEqual(self.inventory.quantity,2)
        dashboard=self.client.get('/api/dashboard').json()
        day=next(d for d in dashboard['pulse'] if d['date']==self.day.isoformat())
        self.assertTrue(day['isMakeup']);self.assertFalse(day['canSubmit'])
        self.assertFalse(day['makeupOpen']);self.assertEqual(dashboard['streakDays'],1)
        # Removing the training submission never reopens the spent permission.
        Submission.objects.filter(member=self.author_member).delete()
        self.assertEqual(self.submit(self.day).status_code,409)

    def test_failed_submission_keeps_permission_without_spending_again(self):
        self.makeup(self.day.isoformat())
        self.assertEqual(self.submit(self.day, proof='').status_code,400)
        with patch('club.views.refresh_totals',side_effect=RuntimeError('temporary failure')):
            with self.assertRaises(RuntimeError): self.submit(self.day)
        self.assertIsNone(MakeupPermission.objects.get(member=self.author_member).completed_at)
        self.assertFalse(CheckinRecord.objects.filter(member=self.author_member).exists())
        self.assertFalse(Submission.objects.filter(member=self.author_member).exists())
        self.assertEqual(self.submit(self.day).status_code,201)
        self.inventory.refresh_from_db();self.assertEqual(self.inventory.quantity,2)

    def test_paid_permission_survives_closed_week_and_later_submission(self):
        day=timezone.localdate()-timedelta(days=10)
        self.makeup(day.isoformat())
        self.semester.weeks.filter(ends_at__lte=timezone.now()).update(is_closed=True)
        with patch('django.utils.timezone.now',return_value=timezone.now()+timedelta(days=8)):
            response=self.submit(day)
        self.assertEqual(response.status_code,201,response.content)
        submission=Submission.objects.get(member=self.author_member)
        self.assertEqual(submission.record_date,day)
        self.assertEqual(submission.week_id,self.semester.weeks.get(starts_at__date__lte=day,ends_at__date__gt=day).pk)

    def test_permission_is_not_usable_after_semester_ends(self):
        self.makeup(self.day.isoformat())
        with patch('django.utils.timezone.now',return_value=timezone.now()+timedelta(days=60)):
            self.client.force_login(self.author)
            self.assertEqual(self.submit(self.day).status_code,409)
        self.assertIsNone(MakeupPermission.objects.get(member=self.author_member).completed_at)

    def test_missing_ticket_guides_purchase_but_does_not_open_permission(self):
        self.inventory.quantity=0;self.inventory.save()
        response=self.makeup(self.day.isoformat())
        self.assertEqual(response.status_code,400)
        self.assertEqual(response.json()['error_code'],'INSUFFICIENT_MAKEUP_TICKETS')
        self.assertEqual(response.json()['item_id'],self.ticket.pk)
        self.assertFalse(MakeupPermission.objects.exists())
        self.ticket.is_active=False;self.ticket.save()
        self.assertIsNone(self.makeup(self.day.isoformat()).json()['item_id'])

    def test_owned_delisted_ticket_is_usable_and_spend_is_atomic(self):
        self.ticket.is_active=False;self.ticket.save()
        self.assertEqual(self.makeup(self.day.isoformat()).status_code,200)
        with patch('club.currency_services.MakeupPermission.objects.create',side_effect=RuntimeError('storage error')):
            with self.assertRaises(RuntimeError): makeup_checkin(self.author_member,self.day-timedelta(days=1))
        self.inventory.refresh_from_db();self.assertEqual(self.inventory.quantity,2)

    def test_invalid_outside_semester_future_today_and_nonmember(self):
        for day in ['2000-01-01',timezone.localdate().isoformat(),(timezone.localdate()+timedelta(days=1)).isoformat(),'bad',123,[]]:
            self.assertEqual(self.makeup(day).status_code,400)
        self.inventory.refresh_from_db();self.assertEqual(self.inventory.quantity,3)
        self.client.logout();self.assertEqual(self.makeup(self.day.isoformat()).status_code,401)
        self.client.force_login(self.reader)
        self.assertEqual(self.submit(self.day).status_code,409)

    def test_historical_submission_needs_permission_today_is_unlimited(self):
        self.assertEqual(self.submit(self.day).status_code,409)
        today=timezone.localdate()
        for _ in range(3):
            response=self.submit(today)
            self.assertEqual(response.status_code,201,response.content)
        self.assertEqual(Submission.objects.filter(member=self.author_member).count(),3)
        self.assertTrue(next(d for d in self.client.get('/api/dashboard').json()['pulse'] if d['isToday'])['canSubmit'])
        self.inventory.refresh_from_db();self.assertEqual(self.inventory.quantity,3)

    def test_completed_submission_recalculates_natural_week_rewards_once(self):
        # Use a historical Monday-Wednesday hole regardless of today's weekday.
        monday=(timezone.localdate()-timedelta(days=7))
        monday-=timedelta(days=monday.weekday())
        day=monday+timedelta(days=1)
        for offset in (0,2):
            CheckinRecord.objects.create(team=self.team,member=self.author_member,checkin_date=monday+timedelta(days=offset))
        StreakReward.objects.create(team=self.team,days=3,reward=4)
        self.makeup(day.isoformat())
        self.assertFalse(WeeklyStreakGrant.objects.filter(member=self.author_member).exists())
        self.assertEqual(self.submit(day).status_code,201)
        self.assertEqual(WeeklyStreakGrant.objects.get(member=self.author_member).amount,4)
        self.assertEqual(self.submit(day).status_code,409)
        self.assertEqual(WeeklyStreakGrant.objects.filter(member=self.author_member).count(),1)
