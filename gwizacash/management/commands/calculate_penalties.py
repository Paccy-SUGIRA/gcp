# gwizacash/management/commands/calculate_penalties.py

# gwizacash/management/commands/calculate_penalties.py

from django.core.management.base import BaseCommand
from django.utils import timezone
from gwizacash.models import Loan, Penalty, MonthlyDeadline, MonthlySharePayment, UserProfile, Transaction
from decimal import Decimal
from django.db import transaction
from datetime import datetime, timedelta
from gwizacash.views import calculate_penalty
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Calculate penalties for late loans and share payments'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            help='Specify date for penalty calculation (YYYY-MM-DD)',
        )

    def handle(self, *args, **kwargs):
        # Determine today
        date_str = kwargs.get('date')
        if date_str:
            today = datetime.strptime(date_str, "%Y-%m-%d").date()
        else:
            today = timezone.now().date()

        penalties_created = 0
        penalties_updated = 0

        with transaction.atomic():
            # ----- Share Payment Penalties -----
            deadlines = MonthlyDeadline.objects.all().order_by('month')
            for deadline in deadlines:
                # Construct exact deadline date
                try:
                    naive_deadline = deadline.month.replace(day=deadline.deadline_day)
                except ValueError:
                    naive_deadline = deadline.month.replace(day=1) + timedelta(days=deadline.deadline_day - 1)

                deadline_date = timezone.make_aware(datetime.combine(naive_deadline, datetime.min.time())).date()

                # Skip deadlines after today
                if today <= deadline_date:
                    continue

                # Loop through all committed users
                for profile in UserProfile.objects.filter(committed_shares__gt=0).select_related('user'):
                    payment = MonthlySharePayment.objects.filter(
                        user=profile.user,
                        payment_month=deadline.month
                    ).first()
                    missing_shares = profile.committed_shares - (payment.shares_paid if payment else 0)
                    if missing_shares <= 0:
                        continue

                    days_late = max(1, (today - deadline_date).days)
                    penalty_amount = calculate_penalty(days_late, missing_shares)

                    # Check existing penalty
                    existing_penalty = Penalty.objects.filter(
                        user=profile.user,
                        penalty_type='LATE_DEPOSIT',
                        original_due_date=deadline_date,
                        is_paid=False
                    ).first()

                    if existing_penalty:
                        if existing_penalty.amount != penalty_amount:
                            existing_penalty.amount = penalty_amount.quantize(Decimal('0.01'))
                            existing_penalty.days_late = days_late
                            existing_penalty.save()
                            Transaction.objects.filter(reference_id=f'FINE-{existing_penalty.id}').update(
                                amount=penalty_amount,
                                description=f'Fine for late payment: {missing_shares} shares, {days_late} days late'
                            )
                            penalties_updated += 1
                    else:
                        penalty = Penalty.objects.create(
                            user=profile.user,
                            penalty_type='LATE_DEPOSIT',
                            amount=penalty_amount.quantize(Decimal('0.01')),
                            days_late=days_late,
                            original_due_date=deadline_date,
                            description=f'Late payment for {missing_shares} shares'
                        )
                        Transaction.objects.create(
                            user=profile.user,
                            transaction_type='PENALTY',
                            amount=penalty_amount,
                            status='PENDING',
                            reference_id=f'FINE-{penalty.id}',
                            description=f'Fine for late payment: {missing_shares} shares, {days_late} days late'
                        )
                        penalties_created += 1

            # ----- Loan Penalties -----
            loans = Loan.objects.filter(status__in=['APPROVED', 'ACTIVE', 'DISBURSED'])
            for loan in loans:
                if today <= loan.due_date.date() or loan.remaining_balance <= 0:
                    continue

                days_late = max(1, (today - loan.due_date.date()).days)
                penalty_amount = calculate_penalty(days_late)

                existing_penalty = Penalty.objects.filter(
                    user=loan.user,
                    penalty_type='LATE_LOAN_REPAYMENT',
                    original_due_date=loan.due_date,
                    is_paid=False
                ).first()

                if existing_penalty:
                    if existing_penalty.amount != penalty_amount:
                        existing_penalty.amount = penalty_amount.quantize(Decimal('0.01'))
                        existing_penalty.days_late = days_late
                        existing_penalty.save()
                        Transaction.objects.filter(reference_id=f'FINE-{existing_penalty.id}').update(
                            amount=penalty_amount,
                            description=f'Fine for late loan repayment: {days_late} days late'
                        )
                        penalties_updated += 1
                else:
                    penalty = Penalty.objects.create(
                        user=loan.user,
                        penalty_type='LATE_LOAN_REPAYMENT',
                        amount=penalty_amount.quantize(Decimal('0.01')),
                        days_late=days_late,
                        original_due_date=loan.due_date,
                        description=f'Late loan repayment - Loan #{loan.id}, {days_late} days late'
                    )
                    Transaction.objects.create(
                        user=loan.user,
                        transaction_type='PENALTY',
                        amount=penalty_amount,
                        status='PENDING',
                        reference_id=f'FINE-{penalty.id}',
                        description=f'Fine for late loan repayment: {days_late} days late'
                    )
                    penalties_created += 1

        self.stdout.write(self.style.SUCCESS(
            f'Created {penalties_created} new penalties, updated {penalties_updated} existing penalties for {today}'
        ))
