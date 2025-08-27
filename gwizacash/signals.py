from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from .models import UserProfile

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        # Only create a profile if one doesn't exist
        UserProfile.objects.get_or_create(
            user=instance,
            defaults={
                'user_type': 'MEMBER',
                'coordinator': UserProfile.objects.filter(user_type='COORDINATOR').first()
            }
        )

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    # Check if profile exists before trying to create it
    try:
        instance.userprofile.save()
    except UserProfile.DoesNotExist:
        UserProfile.objects.create(
            user=instance,
            user_type='MEMBER',
            coordinator=UserProfile.objects.filter(user_type='COORDINATOR').first()
        )
