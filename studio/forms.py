from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from .models import User
class RegistrationForm(UserCreationForm):
    class Meta:
        model=User
        fields=('full_name','email','phone')
    def clean_email(self):
        email=self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists(): raise forms.ValidationError('An account already uses this email.')
        return email
    def save(self,commit=True):
        user=super().save(commit=False)
        user.role='CLIENT'
        user.is_staff=user.is_superuser=False
        if commit: user.save()
        return user
class LoginForm(AuthenticationForm):
    username=forms.EmailField(label='Email',widget=forms.EmailInput(attrs={'autocomplete':'username'}))
    password=forms.CharField(widget=forms.PasswordInput(attrs={'autocomplete':'current-password'}))
    mfa_code=forms.CharField(label='Authenticator or recovery code',required=False,widget=forms.TextInput(attrs={'autocomplete':'one-time-code'}))
