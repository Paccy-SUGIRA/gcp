from django.contrib import admin
from .models import (
    UserProfile, Deposit, Loan, LoanPayment, 
    Transaction, Penalty, ProfitDistribution, 
    MonthlySharePayment, MonthlyDeadline
)

admin.site.register(UserProfile)
admin.site.register(Deposit)
admin.site.register(Loan)
admin.site.register(LoanPayment)
admin.site.register(Transaction)
admin.site.register(Penalty)
admin.site.register(ProfitDistribution)
admin.site.register(MonthlySharePayment)
admin.site.register(MonthlyDeadline)


