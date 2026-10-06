from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.shortcuts import redirect
from .models import User,Service,Project,Enquiry,ProjectFile,Message,PortfolioWork,SiteSetting,Testimonial,Activity
@admin.register(User)
class StudioUserAdmin(UserAdmin):
    ordering=('email',)
    list_display=('email','full_name','role','is_active')
    fieldsets=((None,{'fields':('email','password')}),('Profile',{'fields':('full_name','phone')}),('Permissions',{'fields':('role','is_active','is_staff','is_superuser','groups','user_permissions')}))
    add_fieldsets=((None,{'classes':('wide',),'fields':('email','full_name','password1','password2','role','is_staff')}),)
    search_fields=('email','full_name')
    def get_form(self,request,obj=None,**kwargs):
        form=super().get_form(request,obj,**kwargs)
        return form
for model in [Service,Project,Enquiry,Message,PortfolioWork,SiteSetting,Testimonial]:admin.site.register(model)
# All interactive authentication goes through the shared sign-in screen.
admin.site.login=lambda request,extra_context=None:redirect('/login')
admin.site.has_permission=lambda request:request.user.is_authenticated and request.user.is_studio_admin and request.session.get('mfa_verified',False) and not request.user.must_change_password
