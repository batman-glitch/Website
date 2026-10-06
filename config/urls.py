from django.contrib import admin
from django.urls import path,re_path
from django.shortcuts import redirect
from . import settings
from studio import views
urlpatterns=[
    path('login',views.login_page,name='login'),path('register',views.register_page,name='register'),
    path('password/change',views.password_change),path('password/reset',views.password_reset),
    path('password/reset/<str:uid>/<str:token>/',views.password_confirm,name='password_reset_confirm'),
    path('client/dashboard/',views.client_dashboard),path('dashboard/admin/',views.admin_dashboard),
    path('admin/dashboard/',views.admin_dashboard),path('admin/',admin.site.urls),
    path('api/auth/<str:action>/',views.auth_api),
    path('api/files/<uuid:file_id>/download/',views.download_file),
    path('api/portfolio',views.portfolio_api),path('api/portfolio/',views.portfolio_api),
    path('api/portfolio/<str:part>',views.portfolio_api),path('api/portfolio/<str:part>/',views.portfolio_api),
    path('api/inquiries',views.public_enquiry),path('api/inquiries/',views.public_enquiry),
    path('api/<str:area>/files/<uuid:pk>/',views.managed_api,{'resource':'files'}),
    path('api/<str:area>/<str:resource>/',views.managed_api),
    path('api/<str:area>/<str:resource>/<int:pk>/',views.managed_api),
]
if not settings.PRODUCTION:
    from django.views.static import serve
    urlpatterns += [path('',lambda request:serve(request,'index.html',document_root=settings.BASE_DIR/'Website/cr/outputs')),re_path(r'^assets/(?P<path>.*)$',serve,{'document_root':settings.BASE_DIR/'Website/cr/outputs/assets'})]
