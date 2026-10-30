from django.test import TestCase
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from . import test_community as fixtures
from .models import ExtensionResource, FileDeletion

class ExtensionTests(TestCase):
    setUp = fixtures.CommunityTests.setUp
    image = fixtures.CommunityTests.image

    def test_transparent_cover_uses_theme_blue(self):
        import io
        from PIL import Image
        self.admin()
        image = io.BytesIO()
        Image.new('RGBA', (20, 20), (255, 0, 0, 0)).save(image, 'PNG')
        response = self.client.post('/api/extensions', {'title':'透明封面', 'kind':'link',
            'url':'https://example.com', 'cover':SimpleUploadedFile('transparent.png', image.getvalue(), content_type='image/png')})
        self.assertEqual(response.status_code, 200)
        cover = self.client.get(response.json()['item']['cover'])
        pixel = Image.open(io.BytesIO(b''.join(cover.streaming_content))).getpixel((400, 400))
        self.assertTrue(all(abs(a-b) <= 3 for a,b in zip(pixel, (220,234,255))), pixel)

    def admin(self):
        self.root = User.objects.get(username='admin')
        self.client.force_login(self.root)

    def test_permissions(self):
        self.assertEqual(self.client.get('/api/extensions').status_code, 200)
        for user in [self.author, self.owner]:
            self.client.force_login(user)
            self.assertEqual(self.client.post('/api/extensions', {}).status_code, 403)
            self.assertEqual(self.client.delete('/api/extensions/1').status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get('/api/extensions').status_code, 401)

    def test_files_cover_replace_delete(self):
        self.admin()
        response = self.client.post('/api/extensions', {'title':'下载资料', 'kind':'file',
            'file': SimpleUploadedFile('算法.txt', b'hello'), 'cover':self.image()})
        self.assertEqual(response.status_code, 200, response.content)
        item = response.json()['item']; path = '/api/extensions/' + str(item['id'])
        self.client.force_login(self.author)
        response = self.client.get(item['href'])
        self.assertEqual(b''.join(response.streaming_content), b'hello')
        self.assertIn('attachment;', response['Content-Disposition'])
        self.assertEqual(self.client.get(item['cover'])['Content-Type'], 'image/jpeg')
        self.client.logout()
        self.assertEqual(self.client.get(item['href']).status_code, 401)
        self.client.force_login(self.root)
        self.assertEqual(self.client.post(path, {'title':'链接', 'kind':'link','url':'https://example.com', 'remove_cover':'1'}).status_code, 200)
        self.assertEqual(FileDeletion.objects.count(), 2)
        self.assertEqual(self.client.get(item['href']).status_code, 404)
        self.assertEqual(self.client.delete(path).status_code, 200)
        self.assertFalse(ExtensionResource.objects.exists())

    def test_validation_and_edit_preserve_file(self):
        self.admin()
        for payload in [{'title':'X', 'kind':'link', 'url':'javascript:alert(1)'}, {'title':'X','kind':'file'}, {'title':'X','kind':'link','url':'https://example.com','cover':SimpleUploadedFile('fake.png', b'bad')}]:
            self.assertEqual(self.client.post('/api/extensions', payload).status_code, 400)
        item = self.client.post('/api/extensions', {'title':'X','kind':'file','file':SimpleUploadedFile('a.txt',b'a')}).json()['item']
        response = self.client.post('/api/extensions/'+str(item['id']), {'title':'Y','kind':'file'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['item']['filename'], 'a.txt')
