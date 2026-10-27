from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.db.models.signals import post_save, post_delete, pre_save, pre_delete
from django.dispatch import receiver

from .models import TeamMembership

ORDINARY = '普通用户组'
MANAGERS = '团队管理用户组'


def sync_groups(user_id):
    user = User.objects.filter(pk=user_id).first()
    if not user:
        return
    if user.is_superuser:
        user.groups.clear()
        return
    managing = user.team_memberships.filter(role=TeamMembership.ADMIN, is_active=True).exists()
    group, _ = Group.objects.get_or_create(name=MANAGERS if managing else ORDINARY)
    user.groups.set([group])


@receiver(pre_save, sender=User)
def protect_admin_identity(sender, instance, **kwargs):
    if instance.is_superuser:
        if instance.username != 'admin':
            raise ValidationError('全站只允许一个管理员，固定账号为admin')
        instance.is_staff = True
    else:
        if instance.username == 'admin':
            raise ValidationError('admin为唯一管理员保留账号')
        instance.is_staff = False


@receiver(pre_delete, sender=User)
def protect_admin_deletion(sender, instance, **kwargs):
    if instance.username == 'admin' and instance.is_superuser:
        raise ValidationError('不能删除唯一管理员')


@receiver(post_save, sender=User)
def assign_user_group(sender, instance, raw=False, **kwargs):
    if not raw:
        sync_groups(instance.pk)


@receiver(post_save, sender=TeamMembership)
@receiver(post_delete, sender=TeamMembership)
def assign_membership_group(sender, instance, raw=False, **kwargs):
    if not raw:
        sync_groups(instance.user_id)
