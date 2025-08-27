from django import forms
from django.contrib.auth.forms import UserCreationForm, PasswordChangeForm
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from decimal import Decimal
from .models import Deposit, Loan, LoanPayment, PenaltyPayment, UserProfile



class UserRegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)
    first_name = forms.CharField(max_length=30, required=True)
    last_name = forms.CharField(max_length=30, required=True)
    
    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'password1', 'password2')
    
    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        if commit:
            user.save()
        return user

class DepositForm(forms.ModelForm):
    amount = forms.DecimalField(
        min_value=20000,
        decimal_places=0,
        validators=[MinValueValidator(Decimal('20000'))],
        help_text="Amount must be a multiple of 20,000 RWF (one share)"
    )
    
    class Meta:
        model = Deposit
        fields = ['amount', 'bank_slip']
    
    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount % 20000 != 0:
            raise forms.ValidationError("Amount must be a multiple of 20,000 RWF (one share)")
        return amount

class LoanRequestForm(forms.ModelForm):
    duration = forms.IntegerField(
        min_value=1,
        max_value=24,
        help_text="Loan duration in months (1-24)"
    )
    
    class Meta:
        model = Loan
        fields = ['amount', 'duration']
    
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if self.user:
            max_loan = self.user.userprofile.total_savings
            self.fields['amount'].help_text = f"Maximum eligible amount: {max_loan:,} RWF"
    
    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if self.user and amount > self.user.userprofile.total_savings:
            raise forms.ValidationError("Loan amount exceeds your eligible amount")
        return amount

class LoanPaymentForm(forms.ModelForm):
    class Meta:
        model = LoanPayment
        fields = ['amount', 'bank_slip']
    
    def __init__(self, *args, **kwargs):
        self.loan = kwargs.pop('loan', None)
        super().__init__(*args, **kwargs)
        if self.loan:
            self.fields['amount'].help_text = f"Remaining balance: {self.loan.remaining_balance:,} RWF"
    
    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if self.loan and amount > self.loan.remaining_balance:
            raise forms.ValidationError("Payment amount exceeds the remaining loan balance")
        return amount

class PenaltyPaymentForm(forms.ModelForm):
    class Meta:
        model = PenaltyPayment
        fields = ['amount', 'bank_slip']

    def __init__(self, *args, **kwargs):
        self.penalty = kwargs.pop('penalty', None)
        super().__init__(*args, **kwargs)
        if self.penalty:
            self.fields['amount'].help_text = f"Penalty amount: {self.penalty.amount:,} RWF"
            self.fields['amount'].initial = self.penalty.amount
            self.fields['amount'].widget.attrs['readonly'] = 'readonly'

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if self.penalty and amount != self.penalty.amount:
            raise forms.ValidationError("Amount must match the penalty amount")
        return amount

    def clean_bank_slip(self):
        bank_slip = self.cleaned_data['bank_slip']
        if bank_slip:
            ext = bank_slip.name.split('.')[-1].lower()
            if ext not in ['pdf', 'jpg', 'jpeg', 'png']:
                raise forms.ValidationError("Only PDF, JPG, JPEG, or PNG files are allowed")
            if bank_slip.size > 5 * 1024 * 1024:  # 5MB
                raise forms.ValidationError("File size must not exceed 5MB")
        return bank_slip
    



    from django import forms


# Added


class ProfileUpdateForm(forms.ModelForm):
    """Form for updating user profile with avatar"""
    class Meta:
        model = UserProfile
        fields = ['phone', 'profile_picture']
        widgets = {
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'profile_picture': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
        }
    
    def clean_profile_picture(self):
        picture = self.cleaned_data.get('profile_picture')
        if picture:
            # Check file size (max 2MB)
            if picture.size > 2 * 1024 * 1024:
                raise forms.ValidationError("Image file too large (max 2MB)")
            
            # Check file type
            ext = picture.name.split('.')[-1].lower()
            if ext not in ['jpg', 'jpeg', 'png']:
                raise forms.ValidationError("Only JPG, JPEG, or PNG files allowed")
        
        return picture

class UserUpdateForm(forms.ModelForm):
    """Form for updating user basic info"""
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
        }

class CustomPasswordChangeForm(PasswordChangeForm):
    """Custom password change form with Bootstrap styling"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['old_password'].widget.attrs.update({'class': 'form-control'})
        self.fields['new_password1'].widget.attrs.update({'class': 'form-control'})
        self.fields['new_password2'].widget.attrs.update({'class': 'form-control'})
