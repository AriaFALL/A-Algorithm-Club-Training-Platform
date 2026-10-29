import json
import tempfile
import base64
import io

from PIL import Image

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from .models import Team, TeamMembership, CurrencyBalance, CurrencyTransaction, ShopItem, UserInventory
from .currency_services import initialize_default_currency_config


class CurrencyIntegrationTests(TestCase):
    def setUp(self):
        self.root = User.objects.get(username='admin')
        self.team = Team.objects.create(name='Currency QA', code='CURRENCY', created_by=self.root)
        self.other = Team.objects.create(name='Other QA', code='CURRENCY2', created_by=self.root)
        self.user = User.objects.create_user('currency-member')
        self.member = TeamMembership.objects.create(team=self.team,user=self.user,display_name='Member')
        self.manager_user = User.objects.create_user('currency-manager')
        TeamMembership.objects.create(team=self.team,user=self.manager_user,display_name='Manager',role='admin')
        self.client.force_login(self.root)
        session=self.client.session;session['team_id']=self.team.pk;session.save()

    def post(self, url, data, client=None):
        return (client or self.client).post(url,json.dumps(data),content_type='application/json')

    def config(self, **kwargs):
        data={'team_id':self.team.pk,'currency_enabled':True,'daily_checkin_reward':0,
              'streak_rewards':[{'days':3,'reward':3}],
              'contest_rewards':[{'problems_solved':3,'reward':2,'is_ak':False},{'problems_solved':1,'reward':8,'is_ak':True}]}
        data.update(kwargs)
        return self.post('/api/currency/admin/config',data)

    def test_assets_and_virtual_admin_balance(self):
        self.assertEqual(self.config().status_code,200)
        for path,kind in [('/currency.js','javascript'),('/currency-admin.js','javascript'),('/currency-styles.css','css')]:
            response=self.client.get(path)
            self.assertEqual(response.status_code,200)
            self.assertIn(kind,response['Content-Type'])
        result=self.client.get('/api/currency/balance')
        self.assertEqual(result.status_code,200)
        self.assertFalse(result.json()['can_purchase'])
        self.assertTrue(result.json()['site_admin'])
        self.assertFalse(CurrencyBalance.objects.exists())
        self.assertFalse(self.root.team_memberships.exists())
        self.assertEqual(self.client.get('/api/currency/transactions').json()['transactions'],[])
        self.assertEqual(len(self.client.get('/api/currency/shop/items').json()['items']),1)

    def test_config_targets_explicit_team_and_preserves_empty_rules_and_zero(self):
        result=self.config(team_id=self.other.pk)
        self.assertEqual(result.status_code,200)
        self.team.refresh_from_db();self.other.refresh_from_db()
        self.assertFalse(self.team.currency_enabled)
        self.assertTrue(self.other.currency_enabled)
        data=self.client.get(f'/api/management/teams/{self.other.pk}/settings').json()
        self.assertEqual(data['daily_checkin_reward'],0)
        self.assertEqual(data['streak_rewards'],[{'days':3,'reward':3}])
        self.assertEqual(len(data['contest_rewards']),2)
        self.assertEqual(self.config(team_id=self.other.pk,streak_rewards=[],contest_rewards=[]).status_code,200)
        self.assertEqual(self.post('/api/currency/admin/config',{'team_id':self.other.pk,'currency_enabled':False}).status_code,200)
        self.assertEqual(self.post('/api/currency/admin/config',{'team_id':self.other.pk,'currency_enabled':True}).status_code,200)
        self.assertFalse(self.other.streak_rewards.exists())
        self.assertFalse(self.other.contest_reward_configs.exists())

    def test_invalid_rules_do_not_partially_save(self):
        self.config()
        invalid=[{'daily_checkin_reward':-1},{'currency_enabled':'true'},
                 {'streak_rewards':[{'days':7,'reward':2},{'days':7,'reward':5}]},
                 {'contest_rewards':[{'problems_solved':1,'reward':0,'is_ak':True}]}]
        for fields in invalid:
            with self.subTest(fields=fields):
                self.assertEqual(self.config(**fields).status_code,400)
                self.team.refresh_from_db()
                self.assertEqual(self.team.daily_checkin_reward,0)
                self.assertEqual(list(self.team.streak_rewards.values_list('days',flat=True)),[3])

    def test_only_site_admin_can_configure_adjust_and_manage_shop(self):
        self.config()
        for user in [self.user,self.manager_user]:
            client=Client();client.force_login(user)
            for path in ['/api/currency/admin/config','/api/currency/admin/shop']:
                self.assertEqual(client.get(path).status_code,403)
            self.assertEqual(self.post('/api/currency/admin/adjust',{'member_id':self.member.pk,'amount':3},client).status_code,403)
            self.assertTrue(all('currency_balance' not in r for r in client.get('/api/members').json()['members']))
            self.assertEqual(client.get('/api/currency/balance').status_code,200)

    def test_disabled_team_and_balance_adjustment(self):
        self.config()
        result=self.post('/api/currency/admin/adjust',{'member_id':self.member.pk,'amount':5,'description':'QA'})
        self.assertEqual(result.json()['new_balance'],5)
        rows=self.client.get('/api/members').json()['members']
        self.assertEqual(next(r for r in rows if r['id']==self.member.pk)['currency_balance'],5)
        self.assertEqual(CurrencyTransaction.objects.get().amount,5)
        self.assertEqual(self.post('/api/currency/admin/adjust',{'member_id':self.member.pk,'amount':-6}).status_code,400)
        self.assertEqual(self.post('/api/currency/admin/adjust',{'member_id':self.member.pk,'amount':True}).status_code,400)
        self.assertEqual(self.config(currency_enabled=False).status_code,200)
        self.assertEqual(self.client.get('/api/currency/balance').status_code,403)
        self.assertEqual(self.client.get('/api/currency/shop/items').status_code,403)
        self.assertTrue(all('currency_balance' not in r for r in self.client.get('/api/members').json()['members']))

    def test_icon_upload_serve_and_reject_active_svg(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" fill="#e6b844"/></svg>'
            response=self.config(currency_icon_svg=svg)
            self.assertEqual(response.status_code,200,response.content)
            url=response.json()['currency_icon']
            response=self.client.get(url)
            self.assertEqual(response.status_code,200)
            self.assertIn('sandbox',response['Content-Security-Policy'])
            self.assertEqual(b''.join(response.streaming_content).decode(),svg)
            for bad in ['<svg><script>alert(1)</script></svg>','<svg onload="alert(1)"/>','<svg><use href="https://example.com/a"/></svg>']:
                self.assertEqual(self.config(currency_icon_svg=bad).status_code,400)
            self.assertEqual(self.config(currency_icon_svg=None).status_code,200)
            self.assertEqual(self.client.get(url).status_code,404)

    def test_shop_image_edit_serves_bytes_and_all_lists_use_private_url(self):
        self.config()
        item = ShopItem.objects.get(team=self.team, item_type='makeup_ticket')
        member_client = Client()
        member_client.force_login(self.user)
        with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            for image_format in ['PNG', 'JPEG', 'WEBP']:
                with self.subTest(image_format=image_format):
                    output = io.BytesIO()
                    Image.new('RGB', (3, 3), 'red').save(output, format=image_format)
                    data = output.getvalue()
                    response = self.client.put('/api/currency/admin/shop', json.dumps({
                        'item_id': item.pk,
                        'icon': 'data:image/' + image_format.lower() + ';base64,' + base64.b64encode(data).decode(),
                    }), content_type='application/json')
                    self.assertEqual(response.status_code, 200)
                    url = f'/api/currency/shop/items/{item.pk}/icon'
                    for client, path in [(self.client, '/api/currency/admin/shop'),
                                         (member_client, '/api/currency/shop/items')]:
                        rows = client.get(path).json()['items']
                        self.assertEqual(next(row for row in rows if row['id'] == item.pk)['icon'], url)
                    response = member_client.get(url)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response['Content-Type'], 'image/' + image_format.lower())
                    self.assertEqual(response['Cache-Control'], 'private, no-store')
                    self.assertEqual(b''.join(response.streaming_content), data)
            UserInventory.objects.create(team=self.team, member=self.member, item=item, quantity=1)
            self.assertEqual(member_client.get('/api/currency/inventory').json()['inventory'][0]['icon'], url)
            self.assertEqual(Client().get(url).status_code, 401)
            outsider = User.objects.create_user('image-outsider')
            TeamMembership.objects.create(team=self.other, user=outsider, display_name='Outsider')
            outsider_client = Client(); outsider_client.force_login(outsider)
            self.assertEqual(outsider_client.get(url).status_code, 404)
            self.team.currency_enabled = False
            self.team.save(update_fields=['currency_enabled'])
            self.assertEqual(member_client.get(url).status_code, 404)
            self.team.currency_enabled = True
            self.team.save(update_fields=['currency_enabled'])
            item.refresh_from_db()
            item.icon.storage.delete(item.icon.name)
            self.assertEqual(member_client.get(url).status_code, 404)

    def test_csrf_is_required_and_purchase_updates_balance_and_history(self):
        self.config()
        client=Client(enforce_csrf_checks=True);client.force_login(self.user)
        item=ShopItem.objects.get(team=self.team,item_type='makeup_ticket')
        CurrencyBalance.objects.create(team=self.team,member=self.member,balance=10)
        payload=json.dumps({'item_id':item.pk,'quantity':1})
        self.assertEqual(client.post('/api/currency/shop/purchase',payload,content_type='application/json').status_code,403)
        token=client.get('/api/csrf').json()['csrfToken']
        result=client.post('/api/currency/shop/purchase',payload,content_type='application/json',HTTP_X_CSRFTOKEN=token)
        self.assertEqual(result.status_code,200,result.content)
        self.assertEqual(result.json()['balance'],7)
        self.assertEqual(client.get('/api/currency/transactions').json()['transactions'][0]['amount'],-3)
        result=client.post('/api/currency/shop/purchase',json.dumps({'item_id':item.pk,'quantity':-1}),content_type='application/json',HTTP_X_CSRFTOKEN=token)
        self.assertEqual(result.status_code,400)
