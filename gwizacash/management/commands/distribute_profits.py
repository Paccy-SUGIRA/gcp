#gwizacash/management/commands/distribute_profits.py

from django.core.management.base import BaseCommand
from django.utils import timezone
from decimal import Decimal
from django.db.models import Sum
from gwizacash.models import (
    UserProfile, CollectiveFund, ProfitDistribution, 
    ProfitDistributionSummary, Transaction
)
from django.db import transaction
from datetime import date

class Command(BaseCommand):
    help = 'Distribute monthly profits from interest and penalties to all members with shares'

    def handle(self, *args, **kwargs):
        today = timezone.now().date()
        
        # Check if already distributed this month
        if ProfitDistribution.objects.filter(
            distribution_date__month=today.month, 
            distribution_date__year=today.year
        ).exists():
            self.stdout.write(self.style.WARNING(f"Profits already distributed for {today.strftime('%Y-%m')}"))
            return

        # Get current available profit from CollectiveFund
        fund = CollectiveFund.get_fund()
        fund.update_totals()
        
        if fund.available_profit <= 0:
            self.stdout.write(self.style.WARNING("No profits available for distribution"))
            return

        # Get all members with committed shares (regardless of payment status)
        members_with_shares = UserProfile.objects.filter(committed_shares__gt=0)

        if not members_with_shares.exists():
            self.stdout.write(self.style.WARNING("No members with shares found"))
            return

        try:
            with transaction.atomic():
                total_shares = sum(member.committed_shares for member in members_with_shares)
                per_share_amount = fund.available_profit / total_shares
                
                distribution_time = timezone.now()
                total_distributed = Decimal('0')

                # Distribute to all members with shares
                for profile in members_with_shares:
                    user_profit = per_share_amount * profile.committed_shares
                    
                    ProfitDistribution.objects.create(
                        user=profile.user,
                        distribution_date=distribution_time,
                        total_amount=user_profit,
                        per_share_amount=per_share_amount,
                        source='LOAN_INTEREST_AND_PENALTIES',
                        shares_distributed=profile.committed_shares
                    )
                    
                    Transaction.objects.create(
                        user=profile.user,
                        transaction_type='PROFIT_DISTRIBUTION',
                        amount=user_profit,
                        description=f'Monthly profit for {profile.committed_shares} shares @ {per_share_amount:.2f} RWF/share',
                        date=distribution_time,
                        status='COMPLETED'
                    )
                    
                    # Add to member's savings
                    profile.total_savings += user_profit
                    profile.save()
                    
                    total_distributed += user_profit

                # Create summary record
                ProfitDistributionSummary.objects.create(
                    total_distributed=total_distributed,
                    source='LOAN_INTEREST_AND_PENALTIES'
                )

                # Update fund totals
                fund.update_totals()

                self.stdout.write(self.style.SUCCESS(
                    f'Distributed {total_distributed:,.0f} RWF at {per_share_amount:.2f} RWF/share '
                    f'to {members_with_shares.count()} members on {today.strftime("%B %Y")}'
                ))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error distributing profits: {str(e)}'))
