import json
from unittest.mock import patch
from django.test import TestCase
from . import test_community as fixtures
from .models import Submission, SubmissionPart, SemesterMemberTotal, FileDeletion, SubmissionLike
from .services import refresh_totals


class OwnSubmissionTests(TestCase):
    setUp = fixtures.CommunityTests.setUp
    image = fixtures.CommunityTests.image
    submit = fixtures.CommunityTests.submit

    def test_duplicate_problem_blocked_even_when_rejected_then_allowed_after_delete(self):
        item = self.submit()
        for valid in (True, False):
            item.is_valid = valid
            item.save(update_fields=['is_valid'])
            with patch('club.problem_parser.get_problem', return_value=self.problem):
                response = self.client.post('/api/submissions', {'week_id': self.week.pk,
                    'problem_url': fixtures.URL + '/?from=test', 'proof': self.image()})
            self.assertEqual(response.status_code, 409, response.content)
            self.assertIn('已提交过', response.json()['error'])
        self.assertEqual(Submission.objects.filter(member=self.author_member).count(), 1)
        response = self.client.delete(f'/api/submissions/{item.id}', json.dumps({'version':1}), content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        self.submit()

    def test_edit_cannot_change_to_another_existing_problem(self):
        item = self.submit()
        from .models import Problem
        other_problem = Problem.objects.create(identity='test:other', url='https://example.com/problem/other')
        Submission.objects.create(team=self.team, member=self.author_member, semester=self.semester,
                                  week=self.week, problem=other_problem)
        with patch('club.problem_parser.get_problem', return_value=other_problem):
            response = self.client.post(f'/api/submissions/{item.id}/edit', {'week_id':self.week.pk,
                'version':item.version, 'problem_url':other_problem.url})
        self.assertEqual(response.status_code, 409, response.content)
        item.refresh_from_db()
        self.assertEqual(item.problem_id, self.problem.id)

    def test_edit_reuses_proof_and_recalculates_without_new_count(self):
        item = self.submit()
        original = item.parts.get(kind='proof').upload.name
        date = item.record_date
        SubmissionLike.objects.create(submission=item, user=self.reader)
        response = self.client.post(f'/api/submissions/{item.id}/edit', {'week_id': self.week.id,
            'version': item.version, 'problem_url': fixtures.URL, 'blog': '# 新 Blog'})
        self.assertEqual(response.status_code, 201, response.content)
        item.refresh_from_db()
        self.assertEqual(item.version, 2)
        self.assertEqual(item.record_date, date)
        self.assertEqual(item.parts.get(kind='proof').upload.name, original)
        self.assertEqual(item.parts.get(kind='blog').text_content, '# 新 Blog')
        self.assertFalse(item.likes.exists())
        total = SemesterMemberTotal.objects.get(member=self.author_member)
        self.assertEqual((total.total_score, total.total_submissions), (2, 1))
        self.assertEqual(self.client.post(f'/api/submissions/{item.id}/edit', {'week_id':self.week.id,
            'version':1, 'problem_url':fixtures.URL}).status_code, 409)

    def test_delete_revokes_score_qualification_and_attachment(self):
        item = self.submit()
        proof = item.parts.get(kind='proof')
        self.week.is_closed = True
        self.week.min_score = self.week.min_submissions = 1
        self.week.save()
        refresh_totals(self.semester)
        self.assertGreater(SemesterMemberTotal.objects.get(member=self.author_member).qualified_weeks, 0)
        response = self.client.delete(f'/api/submissions/{item.id}', json.dumps({'version':1}), content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(Submission.objects.filter(pk=item.id).exists())
        total = SemesterMemberTotal.objects.get(member=self.author_member)
        self.assertEqual((total.total_score, total.total_submissions, total.qualified_weeks), (0, 0, 0))
        self.assertTrue(FileDeletion.objects.filter(name=proof.upload.name).exists())
        self.assertEqual(self.client.get(f'/api/attachments/{proof.id}').status_code, 404)
        self.assertEqual(self.client.delete(f'/api/submissions/{item.id}', json.dumps({'version':1}), content_type='application/json').status_code, 404)

    def test_ownership_deadline_archive_and_stale_version(self):
        item = self.submit()
        self.client.force_login(self.reader)
        self.assertEqual(self.client.delete(f'/api/submissions/{item.id}', json.dumps({'version':1}), content_type='application/json').status_code, 404)
        self.assertEqual(self.client.post(f'/api/submissions/{item.id}/edit', {'week_id':self.week.id,
            'version':1, 'problem_url':fixtures.URL}).status_code, 409)
        self.client.force_login(self.author)
        self.assertEqual(self.client.delete(f'/api/submissions/{item.id}', json.dumps({'version':0}), content_type='application/json').status_code, 409)
        self.week.is_closed = True
        self.week.save()
        self.assertEqual(self.client.post(f'/api/submissions/{item.id}/edit', {'week_id':self.week.id,
            'version':1, 'problem_url':fixtures.URL}).status_code, 409)
        from django.utils import timezone
        self.semester.archived_at = timezone.now()
        self.semester.save()
        self.assertEqual(self.client.delete(f'/api/submissions/{item.id}', json.dumps({'version':1}), content_type='application/json').status_code, 409)
