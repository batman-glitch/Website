import base64
import hashlib
import hmac
from datetime import timedelta
from functools import wraps
from cryptography.fernet import Fernet
from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from .models import Throttle

def permission(role=None):
    def decorator(view):
        @wraps(view)
        def wrapped(request,*args,**kwargs):
            if not request.user.is_authenticated:
                if request.path.startswith('/api/'): return JsonResponse({'error':'Sign in to continue.'},status=401)
                return redirect('/login')
            if request.user.role=='ADMIN' and not request.session.get('mfa_verified'):
                return JsonResponse({'error':'Sign in again to verify administrator access.'},status=403)
            if role=='ADMIN' and (not request.user.is_studio_admin or not request.session.get('mfa_verified')):
                return JsonResponse({'error':'Administrator access is required.'},status=403)
            if role=='CLIENT' and request.user.role!='CLIENT':
                return JsonResponse({'error':'Client access is required.'},status=403)
            if request.user.must_change_password and request.path not in ['/api/auth/password/','/api/auth/logout/','/api/auth/session/','/password/change']:
                if request.path.startswith('/api/'):return JsonResponse({'error':'Change your password before continuing.','redirect':'/password/change'},status=403)
                return redirect('/password/change')
            return view(request,*args,**kwargs)
        return wrapped
    return decorator

def throttle(request,scope,limit=8):
    ip=request.META.get('REMOTE_ADDR','unknown')
    if settings.PRODUCTION: ip=request.META.get('HTTP_X_FORWARDED_FOR',ip).split(',')[0].strip()
    digest=hmac.new(settings.SECRET_KEY.encode(),(scope+':'+ip).encode(),hashlib.sha256).hexdigest()
    with transaction.atomic():
        row,_=Throttle.objects.get_or_create(key=digest,defaults={'starts':timezone.now(),'count':0})
        row=Throttle.objects.select_for_update().get(pk=digest)
        if row.starts < timezone.now()-timedelta(minutes=15):row.starts=timezone.now();row.count=0
        row.count+=1;row.save()
        return row.count>limit

def file_cipher():
    key=hashlib.sha256(('private-client-files:'+settings.SECRET_KEY).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))

def verify_mfa(user,code):
    if not user.mfa_enabled:return True
    if not user.legacy_admin_id:return False
    from lib.admin_backend import database,_verify_mfa_code,now_utc
    with database(require_postgres=settings.PRODUCTION) as db:
        return _verify_mfa_code(db,user.legacy_admin_id,user.totp_secret_enc,code,now_utc())
