# gwizacash/urls.py
from django.urls import path
from . import views
from django.conf import settings
from django.conf.urls.static import static

app_name = 'gwizacash'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register, name='register'),
    path('change-password/', views.change_password, name='change_password'),
    path('profile/', views.user_profile, name='user_profile'),
    
    # Deposit URLs
    path('deposit/create/', views.create_deposit, name='create_deposit'),
    path('deposit/pending/', views.pending_deposits, name='pending_deposits'),
    path('deposit/<int:deposit_id>/approve/', views.approve_deposit, name='approve_deposit'),
    path('deposit/<int:deposit_id>/reject/', views.reject_deposit, name='reject_deposit'),
    
    # Loan URLs
    path('loan/request/', views.request_loan, name='request_loan'),
    path('loan/pending/', views.pending_loans, name='pending_loans'),
    path('loan/<int:loan_id>/approve/', views.approve_loan, name='approve_loan'),
    path('loan/<int:loan_id>/disburse/', views.disburse_loan, name='disburse_loan'),
    path('loan/payment/<int:payment_id>/approve/', views.approve_loan_payment, name='approve_loan_payment'),
    path('loan/management/', views.loan_management, name='loan_management'),
    path('loan/my-loans/', views.my_loans, name='my_loans'), 
    path('loan/pay/<int:loan_id>/', views.pay_loan, name='pay_loan'),

    
    # Coordinator URLs
    path('members/', views.manage_members, name='manage_members'),
    path('members/create/', views.create_member, name='create_member'),
    path('members/<int:user_id>/edit/', views.edit_member, name='edit_member'),
    path('members/<int:user_id>/toggle-status/', views.toggle_member_status, name='toggle_member_status'),
    
    # Transaction history
    path('transactions/', views.transaction_history, name='transaction_history'),
  
    # New Group Financials URL
    path('group-financials/', views.group_financials, name='group_financials'),
    
    #profits 
    path('profits/distribute/', views.distribute_profits, name='distribute_profits'),
    
    # Penalty URLs
    path('penalty/pay/<int:penalty_id>/', views.pay_penalty, name='pay_penalty'),
    path('penalty/pending-payments/', views.pending_penalty_payments, name='pending_penalty_payments'),
    path('penalty/approve-payment/<int:payment_id>/', views.approve_penalty_payment, name='approve_penalty_payment'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
