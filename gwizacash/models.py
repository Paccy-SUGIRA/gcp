from datetime import timedelta
from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from decimal import Decimal
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db.models import CheckConstraint, Q

# User profile model
USER_TYPES = (
    ('COORDINATOR', 'Coordinator'),
    ('MEMBER', 'Member'),
)

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    user_type = models.CharField(max_length=20, choices=USER_TYPES)
    coordinator = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True)
    phone = models.CharField(max_length=15, blank=True, null=True)
    first_login = models.BooleanField(default=True)
    profile_picture = models.ImageField(upload_to='profile_pics/', blank=True, null=True)

    # Share-related fields
    committed_shares = models.PositiveIntegerField(default=0, validators=[MinValueValidator(0)])  # FIXED: Added validator
    share_value = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('20000'))
    total_commitment = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    paid_shares = models.PositiveIntegerField(default=0, validators=[MinValueValidator(0)])  # FIXED: Added validator
    remaining_share_balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))

    # Financial fields
    total_savings = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'), validators=[MinValueValidator(0)])  # FIXED: Added validator

    class Meta:
        constraints = [
            CheckConstraint(check=Q(total_savings__gte=0), name='total_savings_non_negative'),
            CheckConstraint(check=Q(remaining_share_balance__gte=0), name='remaining_share_balance_non_negative'),
        ]

    def save(self, *args, **kwargs):
        # FIXED: Ensure consistent calculations
        self.total_commitment = Decimal(self.committed_shares) * self.share_value
        self.remaining_share_balance = self.total_commitment - (Decimal(self.paid_shares) * self.share_value)
        super().save(*args, **kwargs)

    def is_coordinator(self):
        return self.user_type == 'COORDINATOR'

    def get_managed_users(self):
        if self.is_coordinator():
            return UserProfile.objects.filter(coordinator=self)
        return UserProfile.objects.none()


# Deposit model
class Deposit(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected')
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])  # FIXED: Added validator
    date = models.DateTimeField(auto_now_add=True)
    bank_slip = models.FileField(upload_to='bank_slips/')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_deposits')
    approval_date = models.DateTimeField(null=True, blank=True)  # NEW: Added for clarity
    rejection_reason = models.TextField(blank=True, null=True)  # NEW: Added from views
    rejected_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='rejected_deposits')  # NEW: Added from views
    rejection_date = models.DateTimeField(null=True, blank=True)  # NEW: Added from views

    def save(self, *args, **kwargs):
        if self.status == 'APPROVED' and not self.approval_date:
            self.approval_date = timezone.now()
        if self.status == 'REJECTED' and not self.rejection_date:
            self.rejection_date = timezone.now()
        super().save(*args, **kwargs)

# Transaction model
class Transaction(models.Model):
    TRANSACTION_TYPES = [
        ('DEPOSIT', 'Deposit'),
        ('LOAN_REQUEST', 'Loan Request'),
        ('LOAN_DISBURSEMENT', 'Loan Disbursement'),
        ('LOAN_PAYMENT', 'Loan Payment'),
        ('PROFIT_DISTRIBUTION', 'Profit Distribution'),
        ('PENALTY', 'Penalty')
    ]
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('COMPLETED', 'Completed'),
        ('REJECTED', 'Rejected')
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])  # FIXED: Added validator
    date = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    reference_id = models.CharField(max_length=50, blank=True, null=True)
    description = models.TextField(blank=True, null=True)

# Monthly share payment tracking
class MonthlySharePayment(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    payment_month = models.DateField()  # FIXED: Changed to DateField
    shares_paid = models.PositiveIntegerField(default=0, validators=[MinValueValidator(0)])  # FIXED: Added validator
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])  # FIXED: Added validator
    deposit = models.ForeignKey(Deposit, on_delete=models.CASCADE)
    date_created = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'payment_month')
        constraints = [
            CheckConstraint(check=Q(shares_paid__gte=0), name='shares_paid_non_negative'),
            CheckConstraint(check=Q(amount_paid__gte=0), name='amount_paid_non_negative'),
        ]

# FIXED: Simplified signals
@receiver(post_save, sender=User)
def manage_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(
            user=instance,
            defaults={
                'user_type': 'MEMBER',
                'coordinator': UserProfile.objects.filter(user_type='COORDINATOR').first()
            }
        )
    else:
        if hasattr(instance, 'userprofile'):
            instance.userprofile.save()

# Loan model
class Loan(models.Model):
    STATUS = models.TextChoices('Status', 'REQUESTED APPROVED DISBURSED ACTIVE REPAID REJECTED')
        
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    interest_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('5.00'))
    interest_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    remaining_balance = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    status = models.CharField(max_length=20, choices=STATUS.choices, default='REQUESTED')
    duration = models.PositiveIntegerField(default=3)
    request_date = models.DateTimeField(default=timezone.now)
    approval_date = models.DateTimeField(null=True, blank=True)
    disbursement_date = models.DateTimeField(null=True, blank=True)
    due_date = models.DateTimeField(null=True, blank=True)
    
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_loans')
    disbursed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='disbursed_loans')
    
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    @property
    def total_interest(self):
        return self.interest_amount
    
    @property
    def is_overdue(self):
        if self.due_date and self.status in ['DISBURSED', 'ACTIVE']:
            return timezone.now() > self.due_date
        return False
    
    @property
    def days_overdue(self):
        if self.is_overdue:
            return (timezone.now() - self.due_date).days
        return 0
    
    def calculate_penalty(self):
        """Calculate penalty based on days overdue"""
        if not self.is_overdue:
            return Decimal('0')
        
        days = self.days_overdue
        if days == 1:
            return Decimal('2000.00')  # First day: 2000 RWF
        else:
            return Decimal('2000.00') + (Decimal('500.00') * (days - 1))  # Subsequent days: 500 RWF each
    
    def save(self, *args, **kwargs):
        # Set interest rate based on duration
        if self.duration == 3:
            self.interest_rate = Decimal('5.00')
        elif self.duration == 6:
            self.interest_rate = Decimal('5.00')
        elif self.duration == 12:
            self.interest_rate = Decimal('10.00')
        
        # Calculate interest and total amounts
        if not self.interest_amount or not self.total_amount:
            amount = Decimal(str(self.amount))
            interest_rate = Decimal(str(self.interest_rate))
            self.interest_amount = amount * (interest_rate / Decimal('100'))
            self.total_amount = amount + self.interest_amount
        
        if not self.remaining_balance and self.status != 'REPAID':
            self.remaining_balance = self.total_amount

        
        # Set dates based on status changes
        if self.status == 'APPROVED' and not self.approval_date:
            self.approval_date = timezone.now()
        
        if self.status == 'DISBURSED' and not self.disbursement_date:
            self.disbursement_date = timezone.now()
            # Calculate due date from disbursement date
            if not self.due_date:
                self.due_date = self.disbursement_date + timedelta(days=self.duration * 30)
            
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Loan {self.id} - {self.user.username} - {self.amount} RWF"

class CollectiveFund(models.Model):
    """Tracks the collective savings pool of all members"""
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    available_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))  # Total - loans given out
    total_loans_outstanding = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # NEW: Profit tracking fields
    total_profit_earned = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_profit_distributed = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    available_profit = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    last_updated = models.DateTimeField(auto_now=True)

    @classmethod
    def get_fund(cls):
        fund, created = cls.objects.get_or_create(id=1)
        return fund

    def update_totals(self):
        """Recalculate totals from all deposits, penalties, and loans"""
        from django.db.models import Sum
        
        # 1. Total approved deposits (base group savings)
        total_deposits = Deposit.objects.filter(status='APPROVED').aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0')
        
        # 2. Paid penalties (profit source)
        paid_penalties = Penalty.objects.filter(is_paid=True).aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0')
        
        # 3. Interest earned from loan payments
        total_loan_payments = LoanPayment.objects.filter(status='APPROVED').aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0')
        
        # Principal amounts that were repaid
        repaid_loan_principals = Loan.objects.filter(status='REPAID').aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0')
        
        # Interest earned = total payments - principals repaid
        interest_earned = total_loan_payments - repaid_loan_principals
        if interest_earned < 0:
            interest_earned = Decimal('0')
        
        # 4. Outstanding loan principals (money currently loaned out)
        outstanding_loans = Loan.objects.filter(
            status__in=['DISBURSED', 'ACTIVE']
        ).aggregate(
            total=Sum('amount')  # Principal only, not remaining_balance
        )['total'] or Decimal('0')
        
        # 5. Previously distributed profits
        distributed_profits = ProfitDistribution.objects.aggregate(
            total=Sum('total_amount')
        )['total'] or Decimal('0')
        
        # Calculate totals
        self.total_amount = total_deposits + paid_penalties + interest_earned
        self.total_loans_outstanding = outstanding_loans
        self.available_amount = self.total_amount - self.total_loans_outstanding
        
        # Profit calculations
        self.total_profit_earned = paid_penalties + interest_earned
        self.total_profit_distributed = distributed_profits
        self.available_profit = self.total_profit_earned - self.total_profit_distributed
        
        self.save()

    def __str__(self):
        return f"Collective Fund: {self.total_amount} RWF (Available: {self.available_amount} RWF)"

# Loan payment model
class LoanPayment(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected')
    ]
    loan = models.ForeignKey(Loan, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])  # FIXED: Added validator
    payment_date = models.DateTimeField(auto_now_add=True)
    bank_slip = models.FileField(upload_to='payment_slips/')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_payments')  # NEW: Added for tracking
    approval_date = models.DateTimeField(null=True, blank=True)  # NEW: Added for clarity

    def save(self, *args, **kwargs):
        if self.status == 'APPROVED' and not self.approval_date:
            self.approval_date = timezone.now()
        super().save(*args, **kwargs)

# Penalty model
class Penalty(models.Model):
    PENALTY_TYPES = [
        ('LATE_DEPOSIT', 'Late Deposit'),
        ('LATE_LOAN_REPAYMENT', 'Late Loan Repayment'),  # 19 characters
        ('MISSED_MEETING', 'Missed Meeting'),
        ('OTHER', 'Other')
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    penalty_type = models.CharField(max_length=25, choices=PENALTY_TYPES)  # FIXED: Changed from 15 to 25
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    date = models.DateTimeField(auto_now_add=True)
    days_late = models.PositiveIntegerField(default=0, validators=[MinValueValidator(0)])
    original_due_date = models.DateTimeField(null=True, blank=True)
    description = models.TextField(blank=True, null=True)
    is_paid = models.BooleanField(default=False)

# penalty payment
class PenaltyPayment(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected')
    ]
    penalty = models.ForeignKey('Penalty', on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    bank_slip = models.FileField(upload_to='penalty_payment_slips/')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    payment_date = models.DateTimeField(auto_now_add=True)
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_penalty_payments')
    approval_date = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, null=True)
    rejected_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='rejected_penalty_payments')
    rejection_date = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if self.status == 'APPROVED' and not self.approval_date:
            self.approval_date = timezone.now()
        if self.status == 'REJECTED' and not self.rejection_date:
            self.rejection_date = timezone.now()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Payment for Penalty {self.penalty.id} - {self.amount} RWF ({self.status})"

# Profit distribution model
class ProfitDistribution(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='profit_distributions')
    distribution_date = models.DateTimeField()
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    per_share_amount = models.DecimalField(max_digits=10, decimal_places=2)
    source = models.CharField(max_length=50)  # e.g., 'LOAN_INTEREST_AND_PENALTIES'
    shares_distributed = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-distribution_date']

    def __str__(self):
        return f"{self.user.username} - {self.total_amount} RWF on {self.distribution_date.date()}"

class ProfitDistributionSummary(models.Model):
    distribution_date = models.DateField(auto_now_add=True)
    total_distributed = models.DecimalField(max_digits=12, decimal_places=2)
    source = models.CharField(max_length=50)
    
    def __str__(self):
        return f"Summary on {self.distribution_date}: {self.total_distributed} RWF"

# Monthly deadline model
class MonthlyDeadline(models.Model):
    month = models.DateField()
    deadline_day = models.PositiveIntegerField(default=10)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"Deadline for {self.month.strftime('%B %Y')}: {self.deadline_day}"



