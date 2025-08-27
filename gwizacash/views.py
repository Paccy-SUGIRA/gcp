# Authentication Views
from datetime import datetime
from dateutil.relativedelta import relativedelta # type: ignore
from django.db.models import Sum, Count, Q
from django.db import models
from django.utils import timezone
import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum
from django.utils import timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.db import transaction, IntegrityError
from functools import wraps
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
import secrets
from django.contrib.auth import update_session_auth_hash
from django.core.mail import send_mail
from datetime import date, timedelta
from django.core.management import call_command
from .models import CollectiveFund, PenaltyPayment, ProfitDistributionSummary
from .forms import PenaltyPaymentForm
from .forms import ProfileUpdateForm, UserUpdateForm, CustomPasswordChangeForm

from .models import (
    MonthlyDeadline, UserProfile, Deposit, Loan, LoanPayment, 
    Transaction, Penalty, ProfitDistribution, MonthlySharePayment
)
from .forms import (
    UserRegistrationForm, DepositForm, 
    LoanRequestForm, LoanPaymentForm
)
logger = logging.getLogger(__name__)


# File upload validation settings (move to settings.py in production)
ALLOWED_FILE_TYPES = ['pdf', 'jpg', 'jpeg', 'png']
MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5MB

##cordinator required
def coordinator_required(view_func):
    def wrapper(request, *args, **kwargs):
        if request.user.userprofile.user_type != 'COORDINATOR':
            messages.error(request, 'You do not have permission to perform this action')
            return redirect('gwizacash:dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper

# NEW: File validation function
def validate_file(file):
    if file.size > MAX_UPLOAD_SIZE:
        raise ValidationError('File size exceeds 5MB')
    ext = file.name.split('.')[-1].lower()
    if ext not in ALLOWED_FILE_TYPES:
        raise ValidationError('Only PDF, JPG, JPEG, and PNG files are allowed')

# Authentication views

def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            login(request, user)
            messages.success(request, f'Welcome back, {user.get_full_name() or user.username}!')
            return redirect('gwizacash:dashboard')
        else:
            messages.error(request, 'Invalid username or password.')
    
    return render(request, 'gwizacash/login.html')

def logout_view(request):
    logout(request)
    return redirect('gwizacash:login')

def register(request):
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            UserProfile.objects.create(
                user=user,
                user_type='MEMBER',
                coordinator=UserProfile.objects.filter(user_type='COORDINATOR').first()
            )
            login(request, user)
            return redirect('gwizacash:dashboard')
    else:
        form = UserRegistrationForm()
    return render(request, 'gwizacash/register.html', {'form': form})

@login_required
def user_profile(request):
    password_form = None
    
    if request.method == 'POST':
        # Check which form was submitted
        if 'update_profile' in request.POST:
            # Handle profile update
            user_form = UserUpdateForm(request.POST, instance=request.user)
            profile_form = ProfileUpdateForm(request.POST, request.FILES, instance=request.user.userprofile)
            
            if user_form.is_valid() and profile_form.is_valid():
                user_form.save()
                profile_form.save()
                messages.success(request, 'Profile updated successfully')
                return redirect('gwizacash:user_profile')
            else:
                messages.error(request, 'Please correct the profile errors')
                
        elif 'change_password' in request.POST:
            # Handle password change
            password_form = CustomPasswordChangeForm(request.user, request.POST)
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)  # Keep user logged in
                messages.success(request, 'Password changed successfully')
                return redirect('gwizacash:user_profile')
            else:
                messages.error(request, 'Please correct the password errors')
                user_form = UserUpdateForm(instance=request.user)
                profile_form = ProfileUpdateForm(instance=request.user.userprofile)
    else:
        user_form = UserUpdateForm(instance=request.user)
        profile_form = ProfileUpdateForm(instance=request.user.userprofile)
    
    # Initialize password form if not already set
    if password_form is None:
        password_form = CustomPasswordChangeForm(request.user)
    
    context = {
        'user_form': user_form,
        'profile_form': profile_form,
        'password_form': password_form,
    }
    return render(request, 'gwizacash/user_profile.html', context)

@login_required
def change_password(request):
    if not request.user.userprofile.first_login:
        return redirect('gwizacash:dashboard')
            
    if request.method == 'POST':
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')
        
        if len(new_password) < 8:
            messages.error(request, 'Password must be at least 8 characters long')
        elif new_password != confirm_password:
            messages.error(request, 'Passwords do not match')
        else:
            request.user.set_password(new_password)
            request.user.userprofile.first_login = False
            request.user.userprofile.save()
            request.user.save()
            
            # ADD THIS LINE - keeps user logged in
            update_session_auth_hash(request, request.user)
            
            messages.success(request, 'Password changed successfully')
            return redirect('gwizacash:dashboard')
                    
    return render(request, 'gwizacash/change_password.html')

# Dashboard view

@login_required
def dashboard(request):

    user = request.user
    user_profile = user.userprofile
    
    # Initialize all variables at the start
    loan_penalties = 0
    total_penalties = 0
    overdue_loans = []
    user_active_loans = []
    
    # Get user's deposits and calculate totals
    user_deposits = Deposit.objects.filter(user=user, status='APPROVED')
    total_savings = user_profile.total_savings
    
    # Get user's shares information
    committed_shares = user_profile.committed_shares or 0
    paid_shares = user_profile.paid_shares
    share_percentage = (paid_shares / committed_shares * 100) if committed_shares > 0 else 0
    
    # FIXED: Get user's active loans - separate APPROVED from truly active loans
    user_approved_loans = Loan.objects.filter(
        user=user, 
        status='APPROVED'  # Waiting for disbursement
    )
    
    user_active_loans = Loan.objects.filter(
        user=user, 
        status__in=['DISBURSED', 'ACTIVE']  # Actually active loans
    ).order_by('due_date')
    
    # FIXED: Calculate total loan balance only for disbursed/active loans
    total_loan_balance = 0
    for loan in user_active_loans:
        total_loan_balance += loan.remaining_balance
    
    # FIXED: Get overdue loans and calculate penalties - only from active loans
    overdue_loans = []
    loan_penalties = 0
    
    for loan in user_active_loans:
        if loan.is_overdue:
            overdue_loans.append(loan)
            loan_penalties += loan.calculate_penalty()
    
    # Get user penalties (deposit penalties)
    user_penalties = Penalty.objects.filter(user=user, is_paid=False)
    deposit_penalties = user_penalties.aggregate(Sum('amount'))['amount__sum'] or 0
    
    # Calculate total penalties (deposit + loan penalties)
    total_penalties = deposit_penalties + loan_penalties
    
 
    
    # Current month shares calculation
    # Current month shares calculation
    current_month_date = timezone.now().date().replace(day=1)
    has_monthly_payment = MonthlySharePayment.objects.filter(
        user=user,
        payment_month=current_month_date
    ).exists()

    current_month_paid = 1 if has_monthly_payment else 0
    current_month_remaining = 0 if has_monthly_payment else 1

    # Most urgent payment logic
    urgent_payment = None
    urgent_type = None
    urgent_amount = 0
    urgent_date = None

    # 1. Check unpaid penalties (highest priority)
    if total_penalties > 0:
        urgent_payment = "Unpaid Penalties"
        urgent_type = "PENALTY"
        urgent_amount = total_penalties
        urgent_date = timezone.now().date()  # Due immediately

    # 2. Check overdue loans
    elif overdue_loans:
        most_overdue = max(overdue_loans, key=lambda x: x.days_overdue)
        urgent_payment = f"Overdue Loan Payment"
        urgent_type = "OVERDUE_LOAN"
        urgent_amount = most_overdue.remaining_balance
        urgent_date = most_overdue.due_date.date() if most_overdue.due_date else None

    # 3. Check current month deposit
    elif not has_monthly_payment:
        urgent_payment = "Monthly Deposit"
        urgent_type = "MONTHLY_DEPOSIT"
        urgent_amount = user_profile.committed_shares * user_profile.share_value
        urgent_date = timezone.now().date().replace(day=10)  # 10th of current month

    # 4. Check upcoming loan payments this month
    else:
        # Check for loans due this month
        current_month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        current_month_end = (current_month_start + timedelta(days=32)).replace(day=1) - timedelta(seconds=1)
        
        upcoming_loan = user_active_loans.filter(
            due_date__range=[current_month_start, current_month_end]
        ).first()
        
        if upcoming_loan:
            urgent_payment = f"Loan Payment Due"
            urgent_type = "UPCOMING_LOAN"
            urgent_amount = upcoming_loan.remaining_balance
            urgent_date = upcoming_loan.due_date.date() if upcoming_loan.due_date else None
        else:
            # Show next month's payment
            next_month = timezone.now().date().replace(day=1) + timedelta(days=32)
            next_month = next_month.replace(day=10)
            urgent_payment = "Next Monthly Payment"
            urgent_type = "NEXT_PAYMENT"
            urgent_amount = user_profile.committed_shares * user_profile.share_value
            urgent_date = next_month


    # Next payment due date
    next_payment_due = None
    if has_monthly_payment:  # If current month is paid
        next_month = timezone.now().date().replace(day=1) + timedelta(days=32)
        next_month = next_month.replace(day=10)  # 10th of next month
        next_payment_due = next_month


    
    # Recent deposits
    recent_deposits = user_deposits.order_by('-date')[:5]
    
    # Recent transactions - FIXED
    recent_transactions = []
    try:
        recent_transactions = Transaction.objects.filter(
            user=user
        ).order_by('-date')[:10]
    except:
        recent_transactions = []
    
    # Recent profit distributions
    recent_distributions = []
    try:
        recent_distributions = ProfitDistribution.objects.filter(
            user=user
        ).order_by('-distribution_date')[:5]
    except:
        recent_distributions = []

        
    # FIXED: Group financials - only count disbursed/active loans
    collective_fund = CollectiveFund.get_fund()
    collective_fund.update_totals()
    
    group_savings = Deposit.objects.filter(status='APPROVED').aggregate(Sum('amount'))['amount__sum'] or 0
    group_loans = Loan.objects.filter(
        status__in=['DISBURSED', 'ACTIVE']
    ).aggregate(Sum('amount'))['amount__sum'] or 0
    group_distributions = 0  # Calculate based on your profit distribution logic
    
    # Get collective fund
    collective_fund = None
    try:
        collective_fund = CollectiveFund.get_fund()
        collective_fund.update_totals()
    except:
        pass
    
    # Coordinator-specific data
    if user_profile.user_type == 'COORDINATOR':
        total_members = User.objects.filter(userprofile__isnull=False).count()
        members_only = User.objects.filter(userprofile__user_type='MEMBER').count()
        coordinators = User.objects.filter(userprofile__user_type='COORDINATOR').count()
        
        system_total_savings = group_savings
        pending_deposits_count = Deposit.objects.filter(status='PENDING').count()
        
        # FIXED: Loan management stats with proper status handling
        pending_loan_requests = Loan.objects.filter(status='REQUESTED').count()
        approved_loans_count = Loan.objects.filter(status='APPROVED').count()  # Ready for disbursement
        active_loans_count = Loan.objects.filter(status__in=['DISBURSED', 'ACTIVE']).count()
        
        # Fixed: Get pending payments count
        try:
            pending_payments_count = LoanPayment.objects.filter(status='PENDING').count()
        except:
            pending_payments_count = 0
        
        # FIXED: Members with overdue payments (both deposits and loans)
        members_with_overdue_loans = Loan.objects.filter(
            status__in=['DISBURSED', 'ACTIVE'],
            due_date__lt=timezone.now().date()
        ).values('user').distinct().count()
        
        # You can add deposit overdue logic here too
        members_with_overdue_payments = members_with_overdue_loans
        
        total_system_shares = User.objects.filter(
            userprofile__isnull=False
        ).aggregate(
            total=Sum('userprofile__committed_shares')
        )['total'] or 0
    else:
        # Set default values for non-coordinators
        total_members = members_only = coordinators = 0
        system_total_savings = pending_deposits_count = 0
        pending_loan_requests = approved_loans_count = active_loans_count = 0
        pending_payments_count = members_with_overdue_payments = 0
        total_system_shares = 0
    
    context = {
        # User info
        'user_type': user_profile.get_user_type_display(),
        
        # Financial summary
        'total_savings': total_savings,
        'paid_shares': paid_shares,
        'committed_shares': committed_shares,
        'share_percentage': round(share_percentage, 1),
        'total_loan_balance': total_loan_balance,
        'total_penalties': total_penalties,
        'loan_penalties': loan_penalties,
        'next_payment_due': next_payment_due,
        
        # FIXED: Loans - separate approved from active
        'user_approved_loans': user_approved_loans,  # NEW: Loans waiting for disbursement
        'user_active_loans': user_active_loans,      # Only disbursed/active loans
        'overdue_loans': overdue_loans,
        
        # Monthly payment info
        'urgent_payment': urgent_payment,
        'urgent_type' : urgent_type,
        'urgent_amount': urgent_amount,
        'urgent_date': urgent_date,
        'has_monthly_payment': has_monthly_payment,
        'current_month_paid': current_month_paid,
        'current_month_remaining': current_month_remaining,
        
        # Penalties
        'user_penalties': user_penalties,
        
        # Recent activity
        'recent_deposits': recent_deposits,
        'recent_transactions': recent_transactions,
        'recent_distributions': recent_distributions,
        
        # Group financials
        'group_savings': group_savings,
        'group_loans': group_loans,
        'group_distributions': group_distributions,
        'collective_fund': collective_fund,
        
        # Coordinator data
        'total_members': total_members,
        'members_only': members_only,
        'coordinators': coordinators,
        'system_total_savings': system_total_savings,
        'pending_deposits_count': pending_deposits_count,
        'pending_loan_requests': pending_loan_requests,
        'approved_loans_count': approved_loans_count,
        'active_loans_count': active_loans_count,
        'pending_payments_count': pending_payments_count,
        'members_with_overdue_payments': members_with_overdue_payments,
        'total_system_shares': total_system_shares,
    }
    
    return render(request, 'gwizacash/dashboard.html', context)

# Member management views
# UPDATED: Secure password generation and email
@login_required
@coordinator_required
def create_member(request):
    SHARE_VALUE = Decimal('20000')
    
    if request.method == 'POST':
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        email = request.POST.get('email', '')
        phone = request.POST.get('phone', '')
        committed_shares_str = request.POST.get('committed_shares')
        
        if not first_name or not last_name:
            messages.error(request, "First name and last name are required")
            return render(request, 'gwizacash/create_member.html', {'share_value': SHARE_VALUE})
        
        if not committed_shares_str:
            messages.error(request, "Committed shares is required")
            return render(request, 'gwizacash/create_member.html', {'share_value': SHARE_VALUE})
        
        try:
            committed_shares = int(committed_shares_str)
            total_commitment = committed_shares * SHARE_VALUE
            
            full_name = f"{first_name} {last_name}"
            username = f"{first_name.lower()}_{last_name.lower()}"
            
            if User.objects.filter(username=username).exists():
                count = 1
                while User.objects.filter(username=f"{username}_{count}").exists():
                    count += 1
                username = f"{username}_{count}"
            
            password = secrets.token_urlsafe(12)  # Random password
            
            with transaction.atomic():
                user = User.objects.create_user(
                    username=username,
                    password=password,
                    first_name=first_name,
                    last_name=last_name,
                    email=email
                )
                
                profile = user.userprofile
                profile.user_type = 'MEMBER'
                profile.coordinator = request.user.userprofile
                profile.phone = phone
                profile.committed_shares = committed_shares
                profile.share_value = SHARE_VALUE
                profile.total_commitment = total_commitment
                profile.remaining_share_balance = total_commitment
                profile.save()
                
                # Send email with credentials
                if email:
                    try:
                        send_mail(
                            'Welcome to Gwiza-Cash',
                            f'Your account has been created.\nUsername: {username}\nPassword: {password}\nPlease change your password after logging in.',
                            'from@gwizacash.com',
                            [email],
                            fail_silently=True,
                        )
                    except Exception as e:
                        messages.warning(request, f'Failed to send email: {str(e)}')
                
                success_message = f"""
                <div class="text-center mb-3">
                    <i class="bi bi-check-circle-fill text-success fs-1"></i>
                </div>
                <div class="table-responsive">
                    <table class="table table-bordered">
                        <tr><th>Name:</th><td>{full_name}</td></tr>
                        <tr><th>Username:</th><td><code>{username}</code></td></tr>
                        <tr><th>Password:</th><td><code>{password}</code></td></tr>
                        <tr><th>Email:</th><td>{email or 'Not provided'}</td></tr>
                        <tr><th>Phone:</th><td>{phone or 'Not provided'}</td></tr>
                        <tr><th>Committed Shares:</th><td>{committed_shares}</td></tr>
                        <tr><th>Total Commitment:</th><td>{total_commitment:,.2f} RWF</td></tr>
                    </table>
                </div>
                <div class="alert alert-warning mt-3">
                    <strong>Important:</strong> Credentials have been emailed to the member if an email was provided.
                </div>
                """
                
                messages.success(request, success_message)
                return redirect('gwizacash:create_member')
                
        except ValueError:
            messages.error(request, "Committed shares must be a valid number")
        except Exception as e:
            messages.error(request, f"Member creation failed: {str(e)}")
    
    return render(request, 'gwizacash/create_member.html', {'share_value': SHARE_VALUE})

@login_required
@coordinator_required
def manage_members(request):
    assigned_users = UserProfile.objects.filter(
        coordinator=request.user.userprofile
    ).select_related('user')
    
    current_coordinator = request.user.userprofile
    all_users = list(assigned_users) + [current_coordinator]
    
    members_count = assigned_users.filter(user_type='MEMBER').count()
    coordinators_count = assigned_users.filter(user_type='COORDINATOR').count() + 1
    
    total_members = len(all_users)
    total_committed_shares = sum(user.committed_shares for user in all_users)
    total_commitment_amount = sum(user.total_commitment for user in all_users)
    total_paid_shares = sum(user.paid_shares for user in all_users)
    total_remaining_balance = sum(user.remaining_share_balance for user in all_users)
    
    context = {
        'members': all_users,
        'total_members': total_members,
        'members_count': members_count,
        'coordinators_count': coordinators_count,
        'total_committed_shares': total_committed_shares,
        'total_commitment_amount': total_commitment_amount,
        'total_paid_shares': total_paid_shares,
        'total_remaining_balance': total_remaining_balance,
    }
    
    return render(request, 'gwizacash/manage_members.html', context)

@login_required
@coordinator_required
def edit_member(request, user_id):
    member = get_object_or_404(
        UserProfile, 
        user_id=user_id, 
        user_type='MEMBER',
        coordinator=request.user.userprofile
    )
    
    if request.method == 'POST':
        member.user.first_name = request.POST.get('first_name')
        member.user.last_name = request.POST.get('last_name')
        member.phone = request.POST.get('phone')
        member.user.save()
        member.save()
        
        messages.success(request, 'Member updated successfully')
        return redirect('gwizacash:manage_members')
        
    context = {
        'member': member
    }
    return render(request, 'gwizacash/edit_member.html', context)

@login_required
@coordinator_required
def toggle_member_status(request, user_id):
    member = get_object_or_404(
        UserProfile, 
        user_id=user_id, 
        user_type='MEMBER',
        coordinator=request.user.userprofile
    )
    member.user.is_active = not member.user.is_active
    member.user.save()
    
    status = 'activated' if member.user.is_active else 'deactivated'
    messages.success(request, f'Member {member.user.username} has been {status}')
    
    return redirect('gwizacash:manage_members')

# Deposit views
@login_required
def create_deposit(request):
    user_profile = request.user.userprofile
    remaining_shares = user_profile.committed_shares - user_profile.paid_shares
    expected_amount = user_profile.remaining_share_balance.quantize(Decimal('0.01'))
   ##added and not tested for not multideposit
    if Deposit.objects.filter(user=request.user, status='PENDING').exists():
        messages.error(request, 'You already have a pending deposit')
        return redirect('gwizacash:dashboard')
##yet to be tested
    if request.method == 'POST':
        amount = request.POST.get('amount')
        bank_slip = request.FILES.get('bank_slip')

        if amount and bank_slip:
            try:
                validate_file(bank_slip)
                amount = Decimal(amount).quantize(Decimal('0.01'))

                if amount != expected_amount:
                    messages.error(request, f"You must deposit exactly {expected_amount:,.2f} RWF based on your committed shares.")
                else:
                    Deposit.objects.create(
                        user=request.user,
                        amount=amount,
                        bank_slip=bank_slip,
                        status='PENDING'
                    )
                    messages.success(request, 'Deposit submitted successfully and is pending approval')
                    return redirect('gwizacash:dashboard')
            except ValidationError as e:
                messages.error(request, str(e))
            except (ValueError, InvalidOperation):
                messages.error(request, 'Invalid amount')
        else:
            messages.error(request, 'Please provide both amount and bank slip')

    context = {
        'remaining_shares': remaining_shares,
        'max_deposit': expected_amount
    }

    return render(request, 'gwizacash/create_deposit.html', context)

@login_required
def pending_deposits(request):
    print(f"Current user: {request.user.username}")
    print(f"User type: {request.user.userprofile.user_type}")
    
    if request.user.userprofile.user_type != 'COORDINATOR':
        messages.error(request, 'You do not have permission to access this page')
        return redirect('gwizacash:dashboard')
    
    pending_deposits = Deposit.objects.filter(status='PENDING').order_by('-date')
    print(f"Found {pending_deposits.count()} pending deposits")
    
    for deposit in pending_deposits:
        print(f"Deposit: {deposit.id}, User: {deposit.user.username}, Amount: {deposit.amount}")
    
    paginator = Paginator(pending_deposits, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    print(f"Page obj has {len(page_obj)} items")
    
    context = {
        'page_obj': page_obj
    }
    
    return render(request, 'gwizacash/pending_deposits.html', context)

@login_required
def approve_deposit(request, deposit_id):
    if request.user.userprofile.user_type != 'COORDINATOR':
        messages.error(request, 'You do not have permission to perform this action')
        return redirect('gwizacash:pending_deposits')
    
    if request.method == 'POST':
        try:
            with transaction.atomic():
                deposit = get_object_or_404(Deposit.objects.select_for_update(), id=deposit_id, status='PENDING')
                user_profile = UserProfile.objects.select_for_update().get(user=deposit.user)
                
                # Calculate shares based on remaining balance
                remaining_shares = user_profile.committed_shares - user_profile.paid_shares
                
                # Approve the deposit    
                deposit.status = 'APPROVED'
                deposit.approved_by = request.user
                deposit.approval_date = timezone.now()
                deposit.save()
                
                # Update user profile - add ALL remaining shares since amount equals remaining balance
                user_profile.paid_shares += remaining_shares
                user_profile.total_savings += deposit.amount
                user_profile.save()  # This will recalculate remaining_share_balance to 0

                payment_month = timezone.now().date().replace(day=1)
                MonthlySharePayment.objects.create(
                    user=deposit.user,
                    payment_month=payment_month,
                    shares_paid=remaining_shares,
                    amount_paid=deposit.amount,
                    deposit=deposit
                )

                Transaction.objects.create(
                    user=deposit.user,
                    transaction_type='DEPOSIT',
                    amount=deposit.amount,
                    status='COMPLETED',
                    reference_id=f'DEP-{deposit.id}',
               
                )

                messages.success(request, f'Deposit of {deposit.amount:,.2f} RWF approved and recorded')

        except Deposit.DoesNotExist:
            messages.error(request, 'Deposit not found or already processed')
        except Exception as e:
            messages.error(request, f'Error approving deposit: {str(e)}')

    return redirect('gwizacash:pending_deposits')

@login_required
def reject_deposit(request, deposit_id):
    if request.user.userprofile.user_type != 'COORDINATOR':
        messages.error(request, 'You do not have permission to perform this action')
        return redirect('gwizacash:dashboard')
    
    if request.method == 'POST':
        rejection_reason = request.POST.get('rejection_reason', '')
        
        try:
            deposit = Deposit.objects.get(id=deposit_id, status='PENDING')
            
            deposit.status = 'REJECTED'
            deposit.rejection_reason = rejection_reason
            deposit.rejected_by = request.user
            deposit.rejection_date = timezone.now()
            deposit.save()
            
            messages.success(request, f'Deposit of {deposit.amount:,.2f} RWF has been rejected')
        except Deposit.DoesNotExist:
            messages.error(request, 'Deposit not found or already processed')
    
    return redirect('gwizacash:pending_deposits')

# Loan management views

@login_required
def request_loan(request):
    # Check if user has any active, pending, or approved loans FIRST
    existing_loans = Loan.objects.filter(
        user=request.user,
        status__in=['REQUESTED', 'APPROVED', 'DISBURSED', 'ACTIVE']
    ).order_by('-created_at')
    
    if existing_loans.exists():
        # Get the most recent active loan
        latest_loan = existing_loans.first()
        
        # Create appropriate message based on loan status
        if latest_loan.status == 'REQUESTED':
            messages.warning(
                request, 
                f'You already have a loan request pending approval (Loan #{latest_loan.id} for {latest_loan.amount:,.0f} RWF). '
                f'Please wait for approval before requesting another loan.'
            )
        elif latest_loan.status == 'APPROVED':
            messages.warning(
                request, 
                f'You have an approved loan waiting for disbursement (Loan #{latest_loan.id} for {latest_loan.amount:,.0f} RWF). '
                f'You cannot request another loan until this one is processed.'
            )
        elif latest_loan.status in ['DISBURSED', 'ACTIVE']:
            messages.warning(
                request, 
                f'You have an active loan (Loan #{latest_loan.id}) with a remaining balance of '
                f'{latest_loan.remaining_balance:,.0f} RWF. Please complete your current loan before requesting a new one.'
            )
        
        # Redirect to my_loans page to show existing loans
        return redirect('gwizacash:my_loans')
    
    # If no existing loans, proceed with loan request logic
    if request.method == 'POST':
        try:
            amount = Decimal(request.POST.get('amount', '0'))
            duration = int(request.POST.get('duration', '3'))
        except (ValueError, TypeError):
            messages.error(request, 'Invalid amount or duration.')
            return redirect('gwizacash:request_loan')
        
        # Validate duration
        if duration not in [3, 6, 12]:
            messages.error(request, 'Loan duration must be 3, 6, or 12 months.')
            return redirect('gwizacash:request_loan')
        
        # Validate minimum amount
        if amount <= 0:
            messages.error(request, 'Loan amount must be greater than zero.')
            return redirect('gwizacash:request_loan')
        
        # Check savings balance
        try:
            profile = UserProfile.objects.get(user=request.user)
            if amount > profile.total_savings:
                messages.error(
                    request, 
                    f'Loan amount ({amount:,.0f} RWF) cannot exceed your current savings balance ({profile.total_savings:,.0f} RWF).'
                )
                return redirect('gwizacash:request_loan')
        except UserProfile.DoesNotExist:
            messages.error(request, 'User profile not found. Please contact administrator.')
            return redirect('gwizacash:request_loan')
        
        # Calculate interest and total amount
        interest_rate = Decimal('0.05')  # 5% interest rate - adjust as needed
        interest_amount = amount * interest_rate
        total_amount = amount + interest_amount
        
        # Calculate due_date
        due_date = timezone.now() + timedelta(days=duration * 30)
        
        # Create the loan
        loan = Loan.objects.create(
            user=request.user,
            amount=amount,
            duration=duration,
            interest_rate=interest_rate * 100,  # Store as percentage
            interest_amount=interest_amount,
            total_amount=total_amount,
            remaining_balance=total_amount,
            status='REQUESTED',
            request_date=timezone.now(),
            due_date=due_date
        )
        
        messages.success(
            request, 
            f'Loan request for {amount:,.0f} RWF submitted successfully. '
            f'Total amount to repay: {total_amount:,.0f} RWF over {duration} months. '
            f'You will be notified once it is reviewed.'
        )
        return redirect('gwizacash:my_loans')  # Better to redirect to loans page
    
    # GET request - show the form
    # Get user's current savings for display
    try:
        profile = UserProfile.objects.get(user=request.user)
        max_loan_amount = profile.total_savings
    except UserProfile.DoesNotExist:
        max_loan_amount = 0
    
    context = {
        'max_loan_amount': max_loan_amount,
    }
    
    return render(request, 'gwizacash/request_loan.html', context)


@login_required
@coordinator_required
def pending_loans(request):
    loans = Loan.objects.filter(status='REQUESTED').select_related('user', 'user__userprofile')
    paginator = Paginator(loans, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'total_requested_amount': loans.aggregate(Sum('amount'))['amount__sum'] or Decimal('0')
    }
    return render(request, 'gwizacash/pending_loans.html', context)

@login_required
def my_loans(request):
    """Fixed loan display with proper imports"""
    # Get all loans for this user
    user_loans = Loan.objects.filter(user=request.user).order_by('-created_at')
    
    # Get loan payments for this user
    user_loan_payments = LoanPayment.objects.filter(
        loan__user=request.user
    ).select_related('loan', 'approved_by').order_by('-payment_date')
    
    # Separate loans by status with proper categorization
    pending_loans = user_loans.filter(status='REQUESTED')
    approved_loans = user_loans.filter(status='APPROVED')  # Waiting for disbursement
    active_loans = user_loans.filter(status__in=['DISBURSED', 'ACTIVE'])
    completed_loans = user_loans.filter(status='REPAID')
    rejected_loans = user_loans.filter(status='REJECTED')
    
    # FIXED: Calculate summary statistics with proper import
    total_borrowed = user_loans.filter(
        status__in=['DISBURSED', 'ACTIVE', 'REPAID']
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    
    total_remaining = user_loans.filter(
        status__in=['DISBURSED', 'ACTIVE']
    ).aggregate(total=Sum('remaining_balance'))['total'] or Decimal('0')
    
    context = {
        'user_loans': user_loans,
        'pending_loans': pending_loans,
        'approved_loans': approved_loans,
        'active_loans': active_loans,
        'completed_loans': completed_loans,
        'rejected_loans': rejected_loans,
        'loan_payments': user_loan_payments,
        'total_borrowed': total_borrowed,
        'total_remaining': total_remaining,
    }
    
    return render(request, 'gwizacash/my_loans.html', context)

# NEW: View for pending loan payments
@login_required
@coordinator_required
def pending_payments(request):
    if request.user.userprofile.user_type != 'COORDINATOR':
        messages.error(request, 'You do not have permission to access this page')
        return redirect('gwizacash:dashboard')
    
    pending_payments = LoanPayment.objects.filter(
        status='PENDING',
        loan__user__userprofile__coordinator=request.user.userprofile
    ).select_related('loan', 'loan__user')
    
    paginator = Paginator(pending_payments, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj
    }
    return render(request, 'gwizacash/pending_payments.html', context)

@login_required
@coordinator_required
def approve_loan(request, loan_id):
    loan = get_object_or_404(
        Loan,
        id=loan_id,
        status='REQUESTED'
    )
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        with transaction.atomic():
            if action == 'approve':
                # Check if collective fund has enough money
                collective_fund = CollectiveFund.get_fund()
                collective_fund.update_totals()
                
                if loan.amount > collective_fund.available_amount:
                    messages.error(request, f'Insufficient funds in collective pool. Available: {collective_fund.available_amount:,.2f} RWF')
                    return redirect('gwizacash:pending_loans')
                
                loan.status = 'APPROVED'
                loan.approved_by = request.user
                loan.save()  # This will set approval_date automatically
                
                # Create transaction record
                Transaction.objects.create(
                    user=loan.user,
                    transaction_type='LOAN_APPROVAL',
                    amount=loan.amount,
                    status='COMPLETED',
                    reference_id=str(loan.id),
                    description=f'Loan of {loan.amount:,.2f} RWF approved for {loan.duration} months (Interest: {loan.interest_amount:,.2f} RWF)'
                )
                
                messages.success(request, f'Loan approved! Amount: {loan.amount:,.2f} RWF, Interest: {loan.interest_amount:,.2f} RWF, Total: {loan.total_amount:,.2f} RWF')
                
            elif action == 'reject':
                rejection_reason = request.POST.get('rejection_reason', '')
                loan.status = 'REJECTED'
                loan.save()
                
                # Create transaction record
                Transaction.objects.create(
                    user=loan.user,
                    transaction_type='LOAN_REJECTION',
                    amount=loan.amount,
                    status='COMPLETED',
                    reference_id=str(loan.id),
                    description=f'Loan request of {loan.amount:,.2f} RWF rejected. Reason: {rejection_reason}'
                )
                
                messages.success(request, 'Loan request rejected')
    
    return redirect('gwizacash:pending_loans')

@login_required
@coordinator_required
def disburse_loan(request, loan_id):
    """Disburse an approved loan"""
    loan = get_object_or_404(Loan, id=loan_id)
    
    if request.method == 'POST':
        if loan.status != 'APPROVED':
            messages.error(request, 'Only approved loans can be disbursed.')
            return redirect('gwizacash:loan_management')
        
        try:
            # Update loan status to DISBURSED
            loan.status = 'DISBURSED'
            loan.disbursement_date = timezone.now().date()
            loan.due_date = timezone.now().date() + timedelta(days=loan.duration * 30)
            loan.save()
            
            # Create transaction record for disbursement
            Transaction.objects.create(
                user=loan.user,
                transaction_type='LOAN_DISBURSEMENT',
                amount=loan.amount,
                description=f'Loan disbursement for Loan #{loan.id}',
                date=timezone.now().date(),
                status='COMPLETED'
            )
            
            messages.success(
                request, 
                f'Loan #{loan.id} of {loan.amount:,.0f} RWF has been successfully disbursed to {loan.user.get_full_name() or loan.user.username}.'
            )
            
        except Exception as e:
            messages.error(request, f'Error disbursing loan: {str(e)}')
    
    # FIXED: Redirect to the correct URL pattern
    return redirect('gwizacash:loan_management')  # or whatever your correct URL name is

@login_required
@coordinator_required
def approved_loans(request):
    """View to show approved loans ready for disbursement"""
    loans = Loan.objects.filter(
        status='APPROVED'
    ).select_related('user', 'user__userprofile').order_by('-approval_date')
    
    paginator = Paginator(loans, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'collective_fund': CollectiveFund.get_fund()
    }
    return render(request, 'gwizacash/approved_loans.html', context)

@login_required
@coordinator_required
def active_loans(request):
    """View to show active loans and overdue loans"""
    for loan in overdue_loans:
        if loan.is_overdue:
            pass

    active_loans = Loan.objects.filter(
        status__in=['DISBURSED', 'ACTIVE']
    ).select_related('user', 'user__userprofile').order_by('due_date')
    
    # Separate overdue loans
    overdue_loans = [loan for loan in active_loans if loan.is_overdue]
    current_loans = [loan for loan in active_loans if not loan.is_overdue]
    
    context = {
        'current_loans': current_loans,
        'overdue_loans': overdue_loans,
        'collective_fund': CollectiveFund.get_fund()
    }
    return render(request, 'gwizacash/active_loans.html', context)

@login_required
@coordinator_required
def approve_loan_payment(request, payment_id):
    """Approve a loan payment"""
    payment = get_object_or_404(LoanPayment, id=payment_id)
    
    if request.method == 'POST':
        if payment.status != 'PENDING':
            messages.error(request, 'Only pending payments can be approved.')
            return redirect('gwizacash:loan_management')
        
        try:
            # Update payment status
            payment.status = 'APPROVED'
            payment.approved_by = request.user
            payment.approval_date = timezone.now().date()
            payment.save()
            
            # Update loan balance
            loan = payment.loan
            loan.remaining_balance -= payment.amount
            
            # Check if loan is fully paid
            if loan.remaining_balance <= 0:
                loan.status = 'REPAID'
                loan.completion_date = timezone.now().date()
                loan.remaining_balance = 0  # Ensure it's exactly 0
            
            loan.save()
            
            # Create transaction record
            Transaction.objects.create(
                user=loan.user,
                transaction_type='LOAN_PAYMENT',
                amount=payment.amount,
                description=f'Loan payment for Loan #{loan.id}',
                date=payment.payment_date,
                status='COMPLETED'
            )
            
            messages.success(
                request, 
                f'Payment of {payment.amount:,.0f} RWF for Loan #{loan.id} has been approved. '
                f'Remaining balance: {loan.remaining_balance:,.0f} RWF.'
            )
            
        except Exception as e:
            messages.error(request, f'Error approving payment: {str(e)}')
    
    # FIXED: Redirect to the correct URL pattern
    return redirect('gwizacash:loan_management')  # or create a pending_payments view

@login_required
@coordinator_required
def loan_management(request):
    """Combined view for all loan management tasks"""
    # Get all loan data
    pending_loans = Loan.objects.filter(status='REQUESTED').select_related('user', 'user__userprofile')
    approved_loans = Loan.objects.filter(status='APPROVED').select_related('user', 'user__userprofile')
    active_loans = Loan.objects.filter(status__in=['DISBURSED', 'ACTIVE']).select_related('user', 'user__userprofile')
    pending_payments = LoanPayment.objects.filter(status='PENDING').select_related('loan', 'loan__user')
    
    # Separate overdue loans
    overdue_loans = [loan for loan in active_loans if loan.is_overdue]
    current_loans = [loan for loan in active_loans if not loan.is_overdue]
    
    # Get collective fund info
    collective_fund = CollectiveFund.get_fund()
    collective_fund.update_totals()
    
    context = {
        'pending_loans': pending_loans,
        'approved_loans': approved_loans,
        'active_loans': active_loans,
        'current_loans': current_loans,
        'overdue_loans': overdue_loans,
        'pending_payments': pending_payments,
        'collective_fund': collective_fund,
    }
    return render(request, 'gwizacash/loan_management.html', context)

@login_required
def pay_loan(request, loan_id):
    """Improved loan payment processing with proper status transitions"""
    # Fetch loan with validation
    loan = get_object_or_404(
        Loan,
        id=loan_id,
        user=request.user,
        status__in=['DISBURSED', 'ACTIVE']
    )
    
    # Get payment history
    payment_history = LoanPayment.objects.filter(loan=loan).order_by('-payment_date')
    
    # Calculate current payment requirements
    penalty_amount = loan.calculate_penalty() if loan.is_overdue else Decimal('0')
    total_amount_due = loan.remaining_balance + penalty_amount
    
    if request.method == 'POST':
        try:
            amount = Decimal(request.POST.get('amount', '0'))
            bank_slip = request.FILES.get('bank_slip')
            
            # Validate payment amount
            if amount <= 0:
                messages.error(request, 'Payment amount must be greater than 0')
                return redirect('gwizacash:pay_loan', loan_id=loan.id)
            
            if amount > total_amount_due:
                messages.error(request, 
                    f'Payment amount cannot exceed total due: {total_amount_due:,.2f} RWF '
                    f'(Loan: {loan.remaining_balance:,.2f} RWF + Penalty: {penalty_amount:,.2f} RWF)')
                return redirect('gwizacash:pay_loan', loan_id=loan.id)
            
            if not bank_slip:
                messages.error(request, 'Bank slip is required')
                return redirect('gwizacash:pay_loan', loan_id=loan.id)
            
            # Process payment
            with transaction.atomic():
                # Create payment record
                payment = LoanPayment.objects.create(
                    loan=loan,
                    amount=amount,
                    bank_slip=bank_slip,
                    status='PENDING'
                )
                
                # Create transaction record
                Transaction.objects.create(
                    user=request.user,
                    transaction_type='LOAN_PAYMENT',
                    amount=amount,
                    status='PENDING',
                    reference_id=str(payment.id),
                    description=f'Loan payment of {amount:,.2f} RWF for loan #{loan.id}'
                )
                
                # Update loan status to ACTIVE if it's still DISBURSED
                if loan.status == 'DISBURSED':
                    loan.status = 'ACTIVE'
                    loan.save()
                
                messages.success(request, 
                    f'Payment of {amount:,.2f} RWF submitted successfully. '
                    f'Awaiting coordinator approval.')
                
                return redirect('gwizacash:my_loans')
                
        except (ValueError, TypeError) as e:
            messages.error(request, 'Invalid payment amount')
            return redirect('gwizacash:pay_loan', loan_id=loan.id)
    
    # Context for template
    context = {
        'loan': loan,
        'payment_history': payment_history,
        'penalty_amount': penalty_amount,
        'total_amount_due': total_amount_due,
    }
    
    return render(request, 'gwizacash/loan_payment.html', context)

@login_required
def transaction_history(request):
    user_profile = request.user.userprofile

    transactions = Transaction.objects.select_related('user', 'user__userprofile')

    if user_profile.user_type != 'COORDINATOR':
        transactions = transactions.filter(user=request.user)

    # Pagination
    paginator = Paginator(transactions.order_by('-date'), 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    completed_count = transactions.filter(status='COMPLETED').count()
    pending_count = transactions.filter(status='PENDING').count()


    
    share_summary = {
        'committed': user_profile.committed_shares,
        'paid': user_profile.paid_shares,
        'remaining': user_profile.committed_shares - user_profile.paid_shares,
        'total_value': user_profile.total_commitment,
        'paid_value': user_profile.paid_shares * 20000,
        'remaining_value': user_profile.remaining_share_balance
    }

    context = {
        'page_obj': page_obj,
        'transactions': page_obj.object_list,  # for template
        'share_summary': share_summary,
        'is_paginated': page_obj.has_other_pages(),
        'completed_count': completed_count,
        'pending_count': pending_count,
    }

    return render(request, 'gwizacash/transaction_history.html', context)

# Profit distribution views
# NEW: View to show available profits
@login_required
@coordinator_required
def view_profits(request):
    penalty_profits = Penalty.objects.filter(is_paid=True).aggregate(Sum('amount'))['amount__sum'] or Decimal('0')
    loan_interest_profits = Loan.objects.filter(status='PAID').aggregate(Sum('total_interest'))['total_interest__sum'] or Decimal('0')
    total_profits = penalty_profits + loan_interest_profits
    
    context = {
        'penalty_profits': penalty_profits,
        'loan_interest_profits': loan_interest_profits,
        'total_profits': total_profits
    }
    return render(request, 'gwizacash/view_profits.html', context)

# UPDATED: Suggest calculated profits
@login_required
@coordinator_required
def distribute_profits(request):
    today = timezone.now().date()
    this_month = today.month
    this_year = today.year

    already_distributed = ProfitDistribution.objects.filter(
        distribution_date__month=this_month,
        distribution_date__year=this_year
    ).exists()

    # Calculate total profits and shares
    penalty_profits = Penalty.objects.filter(is_paid=True).aggregate(Sum('amount'))['amount__sum'] or Decimal('0')
    loan_profits = Loan.objects.filter(status='PAID').aggregate(Sum('interest_amount'))['interest_amount__sum'] or Decimal('0')
    total_profits = penalty_profits + loan_profits

    total_shares = UserProfile.objects.aggregate(Sum('committed_shares'))['committed_shares__sum'] or 0

    per_share_amount = total_profits / total_shares if total_shares > 0 else Decimal('0')

    if request.method == 'POST':
        if already_distributed:
            messages.warning(request, "Profits for this month have already been distributed.")
            return redirect('gwizacash:distribute_profits')

        if total_shares == 0:
            messages.error(request, 'No committed shares found. Cannot distribute profits.')
            return redirect('gwizacash:distribute_profits')

        distribution_date = timezone.now()

        for profile in UserProfile.objects.filter(committed_shares__gt=0):
            user_profit = per_share_amount * profile.committed_shares
            ProfitDistribution.objects.create(
                user=profile.user,
                distribution_date=distribution_date,
                total_amount=user_profit,
                per_share_amount=per_share_amount,
                source='LOAN_INTEREST_AND_PENALTIES',
                shares_distributed=profile.committed_shares
            )
            Transaction.objects.create(
                user=profile.user,
                transaction_type='PROFIT_DISTRIBUTION',
                amount=user_profit,
                description=f'Profit distribution for {profile.committed_shares} shares at {per_share_amount:.2f} RWF/share',
                date=distribution_date
            )
            profile.total_savings += user_profit
            profile.save()

        messages.success(request, f'Distributed {total_profits:,.0f} RWF at {per_share_amount:,.2f} RWF per share.')
        return redirect('gwizacash:distribute_profits')

    # For GET requests
    last_distribution = ProfitDistribution.objects.order_by('-distribution_date').first()
    next_distribution_date = datetime(today.year, today.month, 2) + relativedelta(months=1)

    context = {
        'recent_distributions': ProfitDistribution.objects.filter(user=request.user)[:5],
        'last_distribution': last_distribution,
        'next_distribution_date': next_distribution_date,
        'already_distributed': already_distributed,
        'total_profits': total_profits,
        'per_share_amount': per_share_amount,
        'loan_profits': loan_profits,
        'penalty_profits': penalty_profits,
        'total_shares': total_shares,
    }
    return render(request, 'gwizacash/distribute_profits.html', context)

# NEW: Group financials view

@login_required
def group_financials(request):
    # Get collective fund with updated totals
    fund = CollectiveFund.get_fund()
    fund.update_totals()
    
    # Existing calculations
    total_savings = UserProfile.objects.aggregate(Sum('total_savings'))['total_savings__sum'] or Decimal('0')
    active_loans = Loan.objects.filter(status__in=['APPROVED', 'ACTIVE', 'DISBURSED']).select_related('user').order_by('-created_at')
    total_loans = active_loans.aggregate(Sum('amount'))['amount__sum'] or Decimal('0')
    total_interest = active_loans.aggregate(Sum('interest_amount'))['interest_amount__sum'] or Decimal('0')
    total_penalties = Penalty.objects.filter(is_paid=True).aggregate(Sum('amount'))['amount__sum'] or Decimal('0')

    # Calculate distribution percentage in the view
    if fund.total_profit_earned > 0:
        distribution_percentage = (fund.total_profit_distributed / fund.total_profit_earned) * 100
    else:
        distribution_percentage = 0
    
    # Recent profit distributions
    recent_distributions = ProfitDistribution.objects.select_related('user').order_by('-distribution_date')[:10]
    
    # Monthly distribution summaries
    distribution_summaries = ProfitDistributionSummary.objects.order_by('-distribution_date')[:6]
    
    paginator = Paginator(active_loans, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'total_group_savings': total_savings,
        'page_obj': page_obj,
        'total_loans': total_loans,
        'total_interest': total_interest,
        'total_penalties': total_penalties,
        
        # NEW: Collective fund metrics
        'collective_fund': fund,
        'total_group_wealth': fund.total_amount,
        'available_cash': fund.available_amount,
        'outstanding_loans': fund.total_loans_outstanding,
        'total_profit_earned': fund.total_profit_earned,
        'total_profit_distributed': fund.total_profit_distributed,
        'available_profit': fund.available_profit,
        
        # NEW: Distribution data
        'recent_distributions': recent_distributions,
        'distribution_summaries': distribution_summaries,
        'distribution_percentage': distribution_percentage,
    }
    return render(request, 'gwizacash/group_financials.html', context)

#penalty payment view
# NEW: Reusable penalty calculation function
def calculate_penalty(days_late, shares=1):
    """Calculate penalty: 2,000 RWF for first day, 500 RWF/day thereafter per share."""
    if days_late < 1:
        return Decimal('0')
    penalty = Decimal('2000')  # First day
    if days_late > 1:
        penalty += Decimal('500') * (days_late - 1)  # Subsequent days
    return penalty * shares

@login_required
@coordinator_required
def pending_penalty_payments(request):
    pending_payments = PenaltyPayment.objects.filter(
        status='PENDING',
        penalty__user__userprofile__coordinator=request.user.userprofile
    ).select_related('penalty', 'penalty__user')
    paginator = Paginator(pending_payments, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    context = {'page_obj': page_obj}
    return render(request, 'gwizacash/pending_penalty_payments.html', context)

@login_required
def pay_penalty(request, penalty_id):
    penalty = get_object_or_404(Penalty, id=penalty_id, user=request.user, is_paid=False)
    # Prevent duplicate submissions
    if PenaltyPayment.objects.filter(penalty=penalty, status='PENDING').exists():
        messages.error(request, 'A payment for this penalty is already pending approval')
        return redirect('gwizacash:dashboard')
    if request.method == 'POST':
        form = PenaltyPaymentForm(request.POST, request.FILES, penalty=penalty)
        if form.is_valid():
            try:
                with transaction.atomic():
                    payment = PenaltyPayment.objects.create(
                        penalty=penalty,
                        amount=form.cleaned_data['amount'],
                        bank_slip=form.cleaned_data['bank_slip'],
                        status='PENDING'
                    )
                    Transaction.objects.create(
                        user=request.user,
                        transaction_type='PENALTY_PAYMENT',
                        amount=payment.amount,
                        status='PENDING',
                        reference_id=f'PENALTY_PAYMENT-{payment.id}',
                        description=f'Payment for penalty {penalty.id}'
                    )
                    messages.success(request, f'Penalty payment of {payment.amount:,.2f} RWF submitted for approval')
                    return redirect('gwizacash:dashboard')
            except Exception as e:
                messages.error(request, f'Error submitting payment: {str(e)}')
        else:
            messages.error(request, 'Invalid form submission')
    else:
        form = PenaltyPaymentForm(penalty=penalty)
    return render(request, 'gwizacash/pay_penalty.html', {'form': form, 'penalty': penalty})

@login_required
@coordinator_required
def approve_penalty_payment(request, payment_id):
    try:
        payment = PenaltyPayment.objects.select_related('penalty', 'penalty__user').get(
            id=payment_id,
            status='PENDING',
            penalty__user__userprofile__coordinator=request.user.userprofile
        )
    except PenaltyPayment.DoesNotExist:
        messages.error(request, "This payment cannot be reviewed.")
        return redirect('gwizacash:pending_penalty_payments')

    if request.method == 'POST':
        action = request.POST.get('action')
        rejection_reason = request.POST.get('rejection_reason', '').strip()
        try:
            with transaction.atomic():
                if action == 'approve':
                    payment.status = 'APPROVED'
                    payment.approved_by = request.user
                    payment.penalty.is_paid = True
                    payment.penalty.save()
                    payment.save()
                    Transaction.objects.filter(
                        reference_id=f'PENALTY_PAYMENT-{payment.id}',
                        transaction_type='PENALTY_PAYMENT'
                    ).update(status='COMPLETED')
                    Transaction.objects.filter(
                        reference_id=f'FINE-{payment.penalty.id}',
                        transaction_type='PENALTY'
                    ).update(status='COMPLETED')
                    messages.success(request, f'Payment of {payment.amount:,.2f} RWF approved')
                elif action == 'reject':
                    if not rejection_reason:
                        messages.error(request, 'Rejection reason is required')
                        return render(request, 'gwizacash/approve_penalty_payment.html', {'payment': payment})
                    payment.status = 'REJECTED'
                    payment.rejection_reason = rejection_reason
                    payment.rejected_by = request.user
                    payment.save()
                    Transaction.objects.filter(
                        reference_id=f'PENALTY_PAYMENT-{payment.id}',
                        transaction_type='PENALTY_PAYMENT'
                    ).update(status='REJECTED')
                    messages.success(request, 'Payment rejected')
                return redirect('gwizacash:pending_penalty_payments')
        except Exception as e:
            messages.error(request, f'Error processing payment: {str(e)}')
    return render(request, 'gwizacash/approve_penalty_payment.html', {'payment': payment})

#check profit distribution
@login_required
@coordinator_required
def check_profit_distribution(request):
    today = timezone.now().date()
    this_month = today.month
    this_year = today.year

    last_distribution = ProfitDistribution.objects.order_by('-distribution_date').first()
    already_distributed = ProfitDistribution.objects.filter(
        distribution_date__year=this_year,
        distribution_date__month=this_month
    ).exists()

    next_distribution_date = datetime(today.year, today.month, 2).date()
    if today.day >= 2:
        if today.month == 12:
            next_distribution_date = datetime(today.year + 1, 1, 2).date()
        else:
            next_distribution_date = datetime(today.year, today.month + 1, 2).date()

    # Optional: calculate potential profits
    loan_profits = Loan.objects.filter(status='PAID').aggregate(
        total_interest=Sum('interest_amount')
    )['total_interest'] or Decimal('0')
    penalty_profits = Penalty.objects.filter(is_paid=True).aggregate(
        total_amount=Sum('amount')
    )['total_amount'] or Decimal('0')
    total_profits = loan_profits + penalty_profits

    total_shares = UserProfile.objects.aggregate(
        total_shares=Sum('committed_shares')
    )['total_shares'] or 0

    per_share_amount = total_profits / total_shares if total_shares > 0 else Decimal('0')

    context = {
        'recent_distributions': ProfitDistribution.objects.filter(user=request.user)[:5], 
        'last_distribution': last_distribution,
        'next_distribution_date': next_distribution_date,
        'already_distributed': already_distributed,
        'total_profits': total_profits,
        'per_share_amount': per_share_amount,
        'next_monthly_deposit_note': "Next deposit due on the 10th of this month"


    }
    return render(request, 'gwizacash/check_profit_distribution.html', context)
