from django.core.management.base import BaseCommand
from gwizacash.models import UserProfile
from django.db import transaction
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Reset monthly shares for all users'

    def handle(self, *args, **kwargs):
        try:
            with transaction.atomic():
                profiles = UserProfile.objects.filter(committed_shares__gt=0)
                for profile in profiles:
                    profile.paid_shares = 0
                    profile.remaining_share_balance = profile.committed_shares * profile.share_value
                    profile.save()
                    logger.info(f"Reset {profile.user.username}: Paid={profile.paid_shares}, Remaining={profile.remaining_share_balance}")
                logger.info(f"Reset {profiles.count()} users")
        except Exception as e:
            logger.error(f"Reset error: {str(e)}")