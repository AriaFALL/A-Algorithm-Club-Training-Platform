from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from django.contrib.auth.models import User
from .models import ContestProblemProgress, Semester
from .solved import archive_submission_credits, remember_contest_ac


@receiver(post_save, sender=ContestProblemProgress)
def contest_ac_saved(sender, instance, raw=False, **kwargs):
    if not raw:
        remember_contest_ac(instance)


@receiver(pre_delete, sender=Semester)
def preserve_semester_solved(sender, instance, origin=None, **kwargs):
    if isinstance(origin, User) or getattr(origin, 'model', None) is User:
        return
    archive_submission_credits(instance)
