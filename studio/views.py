import json
import mimetypes
from decimal import Decimal
from pathlib import Path
from django.conf import settings
from django.contrib.auth import authenticate,login,logout,update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm,PasswordResetForm,SetPasswordForm
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.db import IntegrityError,transaction
from django.http import JsonResponse,HttpResponse,FileResponse
from django.shortcuts import render,redirect,get_object_or_404
from django.middleware.csrf import get_token
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.views.decorators.http import require_http_methods
from .forms import RegistrationForm,LoginForm
from .models import User,Service,Project,Enquiry,ProjectFile,Message,PortfolioWork,SiteSetting,Testimonial,Activity
from .security import permission,throttle,file_cipher,verify_mfa

def response(data,status=200):return JsonResponse(data,status=status)
def csrf_failure(request,reason=''):return response({'error':'Your secure form expired. Refresh and retry.'},403)
def payload(request):
    if len(request.body)>24*1024:raise ValidationError('This update is too large.')
    try:
        data=json.loads(request.body or b'{}')
        if not isinstance(data,dict):raise ValueError()
        return data
    except (ValueError,UnicodeError):raise ValidationError('Send a valid JSON object.')
def user_dict(u):return {'id':u.pk,'email':u.email,'full_name':u.full_name,'phone':u.phone,'role':u.role,'is_active':u.is_active}
def dashboard_url(user):return '/dashboard/admin/' if user.is_studio_admin else '/client/dashboard/'
def activity(request,text,client=None):Activity.objects.create(actor=request.user if request.user.is_authenticated else None,client=client,description=text[:240])
def errors(form):return ' '.join(str(message) for messages in form.errors.values() for message in messages)
def login_account(request,user,code):
    if not verify_mfa(user,code):return False
    login(request,user)
    request.session['mfa_verified']=True
    return True

@require_http_methods(['GET','POST'])
def login_page(request):
    if request.user.is_authenticated:return redirect('/password/change' if request.user.must_change_password else dashboard_url(request.user))
    form=LoginForm(request,data=request.POST or None)
    if request.method=='POST':
        if throttle(request,'login',10):form.add_error(None,'Too many attempts. Try again in 15 minutes.')
        elif form.is_valid():
            user=form.get_user()
            if login_account(request,user,form.cleaned_data.get('mfa_code','')):return redirect('/password/change' if user.must_change_password else dashboard_url(user))
            form.add_error(None,'Check your email, password and authenticator code.')
    return render(request,'studio/auth.html',{'form':form,'mode':'login','recovery_enabled':settings.EMAIL_READY,'title':'Welcome to your studio.','intro':'One account. Everything your project needs.'})

@require_http_methods(['GET','POST'])
def register_page(request):
    if request.user.is_authenticated:return redirect(dashboard_url(request.user))
    form=RegistrationForm(request.POST or None)
    if request.method=='POST':
        if any(k in request.POST for k in ['role','is_staff','is_superuser','groups','user_permissions']):return response({'error':'Account permissions cannot be selected.'},400)
        if throttle(request,'register',5):form.add_error(None,'Please wait before creating another account.')
        elif form.is_valid():
            try:user=form.save()
            except IntegrityError:form.add_error('email','An account already uses this email.')
            else:
                login(request,user,backend='django.contrib.auth.backends.ModelBackend');request.session['mfa_verified']=True
                activity(request,'Joined the studio.',user)
                return redirect('/client/dashboard/')
    return render(request,'studio/auth.html',{'form':form,'mode':'register','title':'Let’s make something great.','intro':'Create a client account to keep your project moving.'})

@permission()
@require_http_methods(['GET','POST'])
def password_change(request):
    form=PasswordChangeForm(request.user,request.POST or None)
    if request.method=='POST' and form.is_valid():
        user=form.save();user.must_change_password=False;user.save(update_fields=['must_change_password']);update_session_auth_hash(request,user)
        return redirect(dashboard_url(user))
    return render(request,'studio/auth.html',{'form':form,'mode':'change','title':'Update your password.','intro':'Use a unique passphrase of at least 14 characters.'})

@require_http_methods(['GET','POST'])
def password_reset(request):
    form=PasswordResetForm(request.POST or None)
    if request.method=='POST':
        if settings.PRODUCTION and not settings.EMAIL_READY:form.add_error(None,'Password recovery email is temporarily unavailable. Contact the studio.')
        elif throttle(request,'reset',5):form.add_error(None,'Please wait before requesting another email.')
        elif form.is_valid():
            try:form.save(request=request,use_https=request.is_secure(),from_email=settings.DEFAULT_FROM_EMAIL,email_template_name='registration/reset_email.txt',subject_template_name='registration/reset_subject.txt')
            except Exception:form.add_error(None,'Email delivery is temporarily unavailable. Try again later.')
            else:return render(request,'studio/auth.html',{'mode':'done','title':'Check your email.','intro':'If an active account matches that email, a recovery link will arrive shortly.'})
    return render(request,'studio/auth.html',{'form':form,'mode':'reset','title':'A fresh start.','intro':'We’ll email a secure link to reset your password.'})

@require_http_methods(['GET','POST'])
def password_confirm(request,uid,token):
    try:user=User.objects.get(pk=force_str(urlsafe_base64_decode(uid)))
    except (ValueError,User.DoesNotExist,OverflowError):user=None
    if not user or not default_token_generator.check_token(user,token):return render(request,'studio/auth.html',{'mode':'done','title':'This link has expired.','intro':'Request a new recovery link.'},status=400)
    form=SetPasswordForm(user,request.POST or None)
    if request.method=='POST' and form.is_valid():
        form.save();user.must_change_password=False;user.save(update_fields=['must_change_password'])
        return redirect('/login')
    return render(request,'studio/auth.html',{'form':form,'mode':'confirm','title':'Choose a new password.','intro':'Use a unique passphrase to protect your studio account.'})

@permission('CLIENT')
def client_dashboard(request):return render(request,'studio/dashboard.html',{'admin_mode':False})
@permission('ADMIN')
def admin_dashboard(request):return render(request,'studio/dashboard.html',{'admin_mode':True})

@require_http_methods(['GET','POST'])
def auth_api(request,action):
    try:
        if action=='session' and request.method=='GET':return response({'authenticated':request.user.is_authenticated,'user':user_dict(request.user) if request.user.is_authenticated else None,'csrfToken':get_token(request),'redirect':dashboard_url(request.user) if request.user.is_authenticated else '/login'})
        if request.method!='POST':return response({'error':'Method not allowed.'},405)
        data=payload(request)
        if action=='register':
            if any(k in data for k in ['role','is_staff','is_superuser','permissions','groups','user_permissions']):return response({'error':'Account permissions cannot be selected.'},400)
            if throttle(request,'register',5):return response({'error':'Too many registration attempts.'},429)
            form=RegistrationForm({'full_name':data.get('full_name',''),'email':data.get('email',''),'phone':data.get('phone',''),'password1':data.get('password',''),'password2':data.get('confirm_password','')})
            if not form.is_valid():return response({'error':errors(form)},400)
            try:user=form.save()
            except IntegrityError:return response({'error':'An account already uses this email.'},400)
            login(request,user,backend='django.contrib.auth.backends.ModelBackend');request.session['mfa_verified']=True;activity(request,'Joined the studio.',user)
            return response({'user':user_dict(user),'redirect':'/client/dashboard/'},201)
        if action=='login':
            if throttle(request,'login',10):return response({'error':'Too many sign-in attempts. Try again in 15 minutes.'},429)
            email=data.get('email','');password=data.get('password','')
            if not isinstance(email,str) or not isinstance(password,str) or len(password)>128:return response({'error':'Check your sign-in details.'},400)
            user=authenticate(request,email=email.strip().lower(),password=password)
            if not user or not login_account(request,user,str(data.get('mfa_code',''))):return response({'error':'Check your email, password and authenticator code.'},401)
            return response({'user':user_dict(user),'redirect':'/password/change' if user.must_change_password else dashboard_url(user)})
        if not request.user.is_authenticated:return response({'error':'Sign in to continue.'},401)
        if action=='logout':logout(request);return response({'redirect':'/login'})
        if action=='password':
            form=PasswordChangeForm(request.user,{'old_password':data.get('current_password'),'new_password1':data.get('new_password'),'new_password2':data.get('confirm_password')})
            if not form.is_valid():return response({'error':errors(form)},400)
            user=form.save();user.must_change_password=False;user.save(update_fields=['must_change_password']);update_session_auth_hash(request,user)
            return response({'ok':True})
        if action=='media-authorize':
            if not request.user.is_studio_admin or not request.session.get('mfa_verified') or request.user.must_change_password:return response({'error':'Administrator access is required.'},403)
            return response({'ok':True})
        return response({'error':'Endpoint not found.'},404)
    except ValidationError as e:return response({'error':' '.join(e.messages)},400)

def project_dict(p):return {'id':p.pk,'name':p.name,'client_id':p.client_id,'client':p.client.full_name,'service_id':p.service_id,'service':p.service.name,'description':p.description,'status':p.status,'start_date':p.start_date,'expected_completion':p.expected_completion,'updated_at':p.updated_at}
def enquiry_dict(e,admin=False):
    result={'id':e.pk,'name':e.name,'email':e.email,'client_id':e.client_id,'project_name':e.project_name,'service':e.service,'message':e.message,'timeline':e.timeline,'genre':e.genre,'status':e.status,'response':e.response,'project_id':e.project_id,'created_at':e.created_at}
    if admin:result['internal_notes']=e.internal_notes
    return result
def service_dict(s):return {'id':s.pk,'name':s.name,'title':s.title,'description':s.description,'price':str(s.price) if s.price is not None else None,'active':s.active,'display_order':s.display_order}
def work_dict(w):return {k:getattr(w,k) for k in ['id','title','artist','service','genre','release_year','description','cover_url','audio_url','audio_label','is_published','is_featured','display_order']}
def file_dict(f):return {'id':str(f.pk),'project_id':f.project_id,'name':f.name,'size':f.size,'uploaded_by':f.uploaded_by.full_name,'created_at':f.created_at,'download_url':'/api/files/'+str(f.pk)+'/download/'}
def message_dict(m):return {'id':m.pk,'client_id':m.client_id,'client':m.client.full_name,'sender':m.sender.full_name,'from_admin':m.sender.role=='ADMIN','body':m.body,'project_id':m.project_id,'created_at':m.created_at}
def save_valid(obj):obj.full_clean();obj.save();return obj

def set_project(p,data):
    if 'client_id' in data:
        client=get_object_or_404(User,pk=data['client_id'],role='CLIENT',is_active=True)
        if p.pk and p.client_id!=client.pk and (p.files.exists() or Message.objects.filter(project=p).exists()):raise ValidationError('A project with private files or messages cannot be reassigned. Create a new project.')
        p.client=client
    if 'service_id' in data:p.service=get_object_or_404(Service,pk=data['service_id'])
    for k in ['name','description','status','start_date','expected_completion']:
        if k in data:setattr(p,k,data[k] or None if k in ['start_date','expected_completion'] else data[k])
    p.full_clean()
    if p.start_date and p.expected_completion and p.expected_completion<p.start_date:raise ValidationError('Completion date must be after the start date.')
    p.save()

def managed_api(request,area,resource,pk=None):
    if area not in ['admin','client']:return response({'error':'Endpoint not found.'},404)
    role='ADMIN' if area=='admin' else 'CLIENT'
    return permission(role)(_managed_api)(request,area,resource,pk)

def _managed_api(request,area,resource,pk=None):
    admin=area=='admin';user=request.user
    try:
        data=payload(request) if request.method in ['POST','PUT','PATCH','DELETE'] and request.content_type=='application/json' else {}
        with transaction.atomic():
            if resource=='overview' and request.method=='GET':
                projects=Project.objects.all() if admin else Project.objects.filter(client=user)
                enquiries=Enquiry.objects.all() if admin else Enquiry.objects.filter(client=user)
                activities=Activity.objects.all() if admin else Activity.objects.filter(client=user)
                stats={'active_projects':projects.exclude(status__in=['completed','cancelled']).count(),'completed_projects':projects.filter(status='completed').count(),'pending_enquiries':enquiries.filter(status='new').count(),'recent_activity':list(activities.order_by('-created_at').values('description','created_at')[:8])}
                if admin:stats.update(total_clients=User.objects.filter(role='CLIENT').count(),new_enquiries=enquiries.filter(status='new').count(),total_services=Service.objects.count(),recent_messages=[message_dict(m) for m in Message.objects.select_related('client','sender').order_by('-created_at')[:5]],recent_files=[file_dict(f) for f in ProjectFile.objects.filter(status='ready').select_related('uploaded_by').order_by('-created_at')[:5]])
                return response(stats)
            if resource=='profile':
                if request.method=='GET':return response({'user':user_dict(user)})
                if request.method in ['PATCH','POST']:
                    if set(data)-{'full_name','phone'}:raise ValidationError('Only name and phone can be updated here.')
                    for k in ['full_name','phone']:
                        if k in data:setattr(user,k,data[k])
                    save_valid(user);return response({'user':user_dict(user)})
            if resource=='projects':
                qs=Project.objects.select_related('client','service').all()
                if not admin:qs=qs.filter(client=user)
                if request.method=='GET':return response({'projects':[project_dict(p) for p in (qs.filter(pk=pk) if pk else qs).order_by('-updated_at')]})
                if not admin:return response({'error':'Project changes require administrator access.'},403)
                if request.method=='POST' and not pk:
                    p=Project();set_project(p,data);activity(request,'Project created: '+p.name,p.client);return response({'project':project_dict(p)},201)
                p=get_object_or_404(qs,pk=pk)
                if request.method in ['PATCH','PUT']:
                    set_project(p,data);activity(request,'Project updated: '+p.name,p.client);return response({'project':project_dict(p)})
                if request.method=='DELETE':activity(request,'Project removed: '+p.name,p.client);p.delete();return response({'ok':True})
            if resource=='enquiries':
                qs=Enquiry.objects.all() if admin else Enquiry.objects.filter(client=user)
                if request.method=='GET':
                    if request.GET.get('status'):qs=qs.filter(status=request.GET['status'])
                    if request.GET.get('q'):
                        from django.db.models import Q
                        q=request.GET['q'];qs=qs.filter(Q(name__icontains=q)|Q(email__icontains=q)|Q(project_name__icontains=q))
                    return response({'enquiries':[enquiry_dict(e,admin) for e in (qs.filter(pk=pk) if pk else qs).order_by('-created_at')[:200]]})
                if request.method=='POST' and not pk:
                    if throttle(request,'enquiry',15):return response({'error':'Please wait before sending another enquiry.'},429)
                    e=Enquiry(client=user if not admin else None,name=user.full_name,email=user.email)
                    for k in ['project_name','service','message','timeline','genre']:
                        if k in data:setattr(e,k,data[k])
                    save_valid(e);activity(request,'Enquiry submitted: '+e.project_name,e.client);return response({'enquiry':enquiry_dict(e,admin)},201)
                if not admin:return response({'error':'Enquiry changes require administrator access.'},403)
                e=get_object_or_404(qs,pk=pk)
                if request.method in ['PATCH','POST']:
                    if 'client_id' in data:e.client=get_object_or_404(User,pk=data['client_id'],role='CLIENT')
                    for k in ['status','response','internal_notes']:
                        if k in data:setattr(e,k,data[k])
                    save_valid(e)
                    if data.get('convert_to_project'):
                        if e.status!='accepted' or not e.client:raise ValidationError('Accept the enquiry and assign a client first.')
                        if e.project_id:return response({'error':'This enquiry already has a project.'},409)
                        service=get_object_or_404(Service,pk=data.get('service_id'))
                        e.project=Project.objects.create(client=e.client,service=service,name=e.project_name or 'New project',description=e.message,status='accepted');e.save(update_fields=['project'])
                    activity(request,'Enquiry updated: '+e.project_name,e.client);return response({'enquiry':enquiry_dict(e,True)})
            if resource=='clients' and admin:
                qs=User.objects.filter(role='CLIENT')
                if request.method=='GET':
                    if request.GET.get('q'):
                        from django.db.models import Q
                        q=request.GET['q'];qs=qs.filter(Q(full_name__icontains=q)|Q(email__icontains=q))
                    if pk:
                        client=get_object_or_404(qs,pk=pk);return response({'client':user_dict(client),'projects':[project_dict(p) for p in client.projects.select_related('client','service')],'enquiries':[enquiry_dict(e,True) for e in client.enquiries.all()]})
                    return response({'clients':[user_dict(c) for c in qs.order_by('-date_joined')[:200]]})
                if request.method=='PATCH':
                    client=get_object_or_404(qs,pk=pk)
                    if set(data)-{'is_active'} or not isinstance(data.get('is_active'),bool):raise ValidationError('Supply a valid account status.')
                    client.is_active=data['is_active'];client.save(update_fields=['is_active']);activity(request,'Client account status updated.',client);return response({'client':user_dict(client)})
            if resource=='messages':
                qs=Message.objects.select_related('client','sender').all()
                if not admin:qs=qs.filter(client=user)
                elif request.GET.get('client_id'):qs=qs.filter(client_id=request.GET['client_id'])
                if request.method=='GET':return response({'messages':[message_dict(m) for m in qs.order_by('created_at')[:300]]})
                if request.method=='POST':
                    if throttle(request,'message',40):return response({'error':'Please wait before sending more messages.'},429)
                    client=get_object_or_404(User,pk=data.get('client_id'),role='CLIENT') if admin else user
                    m=Message(client=client,sender=user,body=data.get('body',''))
                    if data.get('project_id'):m.project=get_object_or_404(Project,pk=data['project_id'],client=client)
                    save_valid(m);activity(request,'New message from '+user.full_name,client);return response({'message':message_dict(m)},201)
            if resource=='files':
                qs=ProjectFile.objects.filter(status='ready').select_related('uploaded_by','project')
                if not admin:qs=qs.filter(project__client=user)
                if request.method=='GET':
                    if request.GET.get('project_id'):qs=qs.filter(project_id=request.GET['project_id'])
                    return response({'files':[file_dict(f) for f in qs.order_by('-created_at')[:200]]})
                if request.method=='POST':
                    if throttle(request,'file',20):return response({'error':'Please wait before uploading more files.'},429)
                    projects=Project.objects.all() if admin else Project.objects.filter(client=user)
                    p=get_object_or_404(projects,pk=request.POST.get('project_id'))
                    if not admin and p.status not in ['accepted','in_progress','review','revision']:return response({'error':'Uploads are closed for this project.'},403)
                    uploaded=request.FILES.get('file')
                    if not uploaded or not 0<uploaded.size<=3*1024*1024:raise ValidationError('Choose a file up to 3 MB. For full sessions, send a transfer link in Messages.')
                    ext=Path(uploaded.name).suffix.lower()
                    if ext not in ['.mp3','.wav','.flac','.m4a','.aac','.ogg','.zip','.pdf','.txt','.jpg','.jpeg','.png','.webp']:raise ValidationError('Choose an audio, image, PDF, text or ZIP file.')
                    name=Path(uploaded.name).name[:160]
                    f=ProjectFile.objects.create(project=p,uploaded_by=user,name=name,content_type=mimetypes.guess_type(name)[0] or 'application/octet-stream',size=uploaded.size,encrypted_content=file_cipher().encrypt(uploaded.read()))
                    activity(request,'File uploaded: '+name,p.client);return response({'file':file_dict(f)},201)
                if request.method=='DELETE' and admin:
                    f=get_object_or_404(qs,pk=pk);f.delete();return response({'ok':True})
            if resource=='services' and admin:
                if request.method=='GET':return response({'services':[service_dict(s) for s in Service.objects.order_by('display_order','id')]})
                s=get_object_or_404(Service,pk=pk) if pk else Service()
                if request.method in ['POST','PUT','PATCH']:
                    for k in ['name','title','description','price','active','display_order']:
                        if k in data:setattr(s,k,data[k] if k!='price' or data[k] else None)
                    save_valid(s);return response({'service':service_dict(s)},200 if pk else 201)
                if request.method=='DELETE':s.active=False;s.save(update_fields=['active']);return response({'ok':True})
            if resource=='portfolio' and admin:
                if request.method=='GET':return response({'projects':[work_dict(w) for w in PortfolioWork.objects.order_by('display_order','-id')]})
                w=get_object_or_404(PortfolioWork,pk=pk) if pk else PortfolioWork()
                if request.method in ['POST','PUT','PATCH']:
                    for k in ['title','artist','service','genre','release_year','description','cover_url','audio_url','audio_label','is_published','is_featured','display_order']:
                        if k in data:setattr(w,k,data[k])
                    for k in ['cover_url','audio_url']:
                        from lib.platform_backend import _safe_media_url
                        setattr(w,k,_safe_media_url(getattr(w,k),k))
                    save_valid(w);return response({'project':work_dict(w)},200 if pk else 201)
                if request.method=='DELETE':w.delete();return response({'ok':True})
            if resource=='testimonials' and admin:
                if request.method=='GET':return response({'testimonials':list(Testimonial.objects.values('id','name','quote','published'))})
                t=get_object_or_404(Testimonial,pk=pk) if pk else Testimonial()
                if request.method in ['POST','PUT','PATCH']:
                    for k in ['name','quote','published']:
                        if k in data:setattr(t,k,data[k])
                    save_valid(t);return response({'ok':True,'id':t.pk})
                if request.method=='DELETE':t.delete();return response({'ok':True})
            if resource=='settings' and admin:
                if request.method=='GET':return response({'settings':dict(SiteSetting.objects.values_list('key','value'))})
                if request.method in ['PUT','POST']:
                    allowed={'heroTitle':90,'heroAccent':90,'heroDescription':500,'availability':120,'aboutText':1200,'contactEmail':254}
                    for k,v in data.items():
                        if k not in allowed or not isinstance(v,str) or not v.strip() or len(v)>allowed[k]:raise ValidationError('Check your site settings.')
                        if k=='contactEmail':
                            from django.core.validators import validate_email
                            validate_email(v)
                        SiteSetting.objects.update_or_create(key=k,defaults={'value':v.strip()})
                    return response({'ok':True})
            return response({'error':'Operation not available.'},405)
    except (ValidationError,ValueError,TypeError,IntegrityError) as e:
        return response({'error':' '.join(e.messages) if isinstance(e,ValidationError) else 'Check the values and try again.'},400)

@permission()
@require_http_methods(['GET'])
def download_file(request,file_id):
    qs=ProjectFile.objects.filter(status='ready')
    if not request.user.is_studio_admin:qs=qs.filter(project__client=request.user)
    f=get_object_or_404(qs,pk=file_id)
    if f.encrypted_content is None:return response({'error':'The file is not available.'},404)
    content=file_cipher().decrypt(bytes(f.encrypted_content))
    from io import BytesIO
    result=FileResponse(BytesIO(content),as_attachment=True,filename=f.name,content_type='application/octet-stream')
    result['X-Content-Type-Options']='nosniff';result['Content-Security-Policy']="default-src 'none'; sandbox"
    return result

@require_http_methods(['GET'])
def portfolio_api(request,part=''):
    from lib.platform_backend import DEFAULT_SETTINGS
    works=[work_dict(w) for w in PortfolioWork.objects.filter(is_published=True).order_by('-is_featured','display_order','-id')]
    services=[service_dict(s) for s in Service.objects.filter(active=True).order_by('display_order','id')]
    if part=='projects':return response({'projects':works})
    if part=='services':return response({'services':services})
    return response({'projects':works,'services':services,'settings':{**DEFAULT_SETTINGS,**dict(SiteSetting.objects.values_list('key','value'))},'testimonials':list(Testimonial.objects.filter(published=True).values('name','quote'))})

@require_http_methods(['POST'])
def public_enquiry(request):
    try:
        if throttle(request,'guest-enquiry',5):return response({'error':'Please wait before sending another enquiry.'},429)
        data=payload(request)
        if data.get('website'):return response({'ok':True},202)
        e=Enquiry(client=request.user if request.user.is_authenticated and request.user.role=='CLIENT' else None)
        for key,target in [('name','name'),('email','email'),('project','project_name'),('service','service'),('timeline','timeline'),('genre','genre'),('message','message')]:setattr(e,target,data.get(key,''))
        if e.client:e.name=request.user.full_name;e.email=request.user.email
        save_valid(e);return response({'ok':True,'id':e.pk},201)
    except ValidationError as e:return response({'error':' '.join(e.messages)},400)
