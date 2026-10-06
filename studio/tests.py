import json
from django.test import TestCase,Client,override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from .models import User,Service,Project,ProjectFile,Enquiry,Message
from .security import file_cipher
PASSWORD='A-long-test-only-Passphrase-729!'
class AccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin=User.objects.create_superuser('studio-admin@example.test',PASSWORD,full_name='Studio Admin')
        cls.a=User.objects.create_user('artist-a@example.test',PASSWORD,full_name='Artist A')
        cls.b=User.objects.create_user('artist-b@example.test',PASSWORD,full_name='Artist B')
        cls.service=Service.objects.create(name='Mixing',title='Mixing')
        cls.project=Project.objects.create(client=cls.a,name='Private record',service=cls.service,status='accepted')
        cls.file=ProjectFile.objects.create(project=cls.project,uploaded_by=cls.a,name='private.txt',size=6,content_type='text/plain',encrypted_content=file_cipher().encrypt(b'secret'))
        cls.enquiry=Enquiry.objects.create(client=cls.a,name='Artist A',email=cls.a.email,service='Mixing',message='Private project details')
        Message.objects.create(client=cls.a,sender=cls.admin,body='Private conversation')
    def signed_in(self,user):
        c=Client();c.force_login(user);s=c.session;s['mfa_verified']=True;s.save();return c
    def post(self,c,url,data,method='post'):return getattr(c,method)(url,data=json.dumps(data),content_type='application/json')
    def test_registration_cannot_escalate_roles(self):
        c=Client()
        for field,value in [('role','ADMIN'),('is_staff',True),('is_superuser',True),('groups',[1])]:
            response=self.post(c,'/api/auth/register/',{'full_name':'Fake','email':'fake@example.test','password':PASSWORD,'confirm_password':PASSWORD,field:value})
            self.assertEqual(response.status_code,400)
        self.assertFalse(User.objects.filter(email='fake@example.test').exists())
    def test_public_registration_assigns_client_and_hashes_password(self):
        c=Client();r=self.post(c,'/api/auth/register/',{'full_name':'New Client','email':'NEW@example.test','phone':'123','password':PASSWORD,'confirm_password':PASSWORD})
        self.assertEqual(r.status_code,201);u=User.objects.get(email='new@example.test')
        self.assertEqual(u.role,'CLIENT');self.assertFalse(u.is_staff);self.assertTrue(u.check_password(PASSWORD));self.assertNotEqual(u.password,PASSWORD);self.assertEqual(r.json()['redirect'],'/client/dashboard/')
    def test_common_login_backend_role_redirects(self):
        for user,destination in [(self.a,'/client/dashboard/'),(self.admin,'/dashboard/admin/')]:
            c=Client();r=self.post(c,'/api/auth/login/',{'email':user.email,'password':PASSWORD});self.assertEqual(r.status_code,200);self.assertEqual(r.json()['redirect'],destination)
    def test_unauthenticated_dashboard_redirect(self):
        for path in ['/client/dashboard/','/dashboard/admin/','/admin/dashboard/']:
            r=self.client.get(path);self.assertEqual(r.status_code,302);self.assertEqual(r.url,'/login')
    def test_client_cannot_access_admin_pages_or_api(self):
        c=self.signed_in(self.a)
        for path in ['/dashboard/admin/','/admin/dashboard/','/api/admin/clients/','/api/admin/projects/']:
            self.assertEqual(c.get(path).status_code,403)
    def test_client_can_only_read_own_resources(self):
        c=self.signed_in(self.b)
        for path,key in [('/api/client/projects/','projects'),('/api/client/enquiries/','enquiries'),('/api/client/messages/','messages'),('/api/client/files/','files')]:self.assertEqual(c.get(path).json()[key],[])
        self.assertEqual(c.get('/api/files/'+str(self.file.pk)+'/download/').status_code,404)
        r=c.post('/api/client/files/',{'project_id':self.project.pk,'file':SimpleUploadedFile('test.txt',b'new')});self.assertEqual(r.status_code,404)
    def test_client_cannot_modify_project_or_other_identity(self):
        c=self.signed_in(self.a)
        self.assertEqual(self.post(c,'/api/client/projects/'+str(self.project.pk)+'/',{'status':'completed'},'patch').status_code,403)
        self.assertEqual(self.post(c,'/api/client/profile/',{'role':'ADMIN'},'patch').status_code,400)
        self.assertEqual(self.post(c,'/api/client/profile/',{'email':self.b.email},'patch').status_code,400)
    def test_private_upload_encrypted_and_owner_download(self):
        c=self.signed_in(self.a);r=c.post('/api/client/files/',{'project_id':self.project.pk,'file':SimpleUploadedFile('notes.txt',b'private new content')})
        self.assertEqual(r.status_code,201);f=ProjectFile.objects.get(pk=r.json()['file']['id']);self.assertNotIn(b'private new content',bytes(f.encrypted_content));self.assertEqual(file_cipher().decrypt(bytes(f.encrypted_content)),b'private new content')
        d=c.get(r.json()['file']['download_url']);self.assertEqual(d.status_code,200);self.assertEqual(b''.join(d.streaming_content),b'private new content');self.assertIn('attachment',d['Content-Disposition'])
    def test_completed_project_blocks_client_upload(self):
        self.project.status='completed';self.project.save();c=self.signed_in(self.a)
        self.assertEqual(c.post('/api/client/files/',{'project_id':self.project.pk,'file':SimpleUploadedFile('test.txt',b'test')}).status_code,403)
    def test_admin_accept_and_convert_enquiry(self):
        c=self.signed_in(self.admin);r=self.post(c,'/api/admin/enquiries/'+str(self.enquiry.pk)+'/',{'status':'accepted','client_id':self.a.pk,'service_id':self.service.pk,'convert_to_project':True},'patch')
        self.assertEqual(r.status_code,200,r.json());self.enquiry.refresh_from_db();self.assertEqual(self.enquiry.project.client,self.a)
        self.assertEqual(self.post(c,'/api/admin/enquiries/'+str(self.enquiry.pk)+'/',{'convert_to_project':True,'service_id':self.service.pk},'patch').status_code,409)
    def test_admin_update_public_services(self):
        c=self.signed_in(self.admin);r=self.post(c,'/api/admin/services/'+str(self.service.pk)+'/',{'description':'Updated public description'},'patch');self.assertEqual(r.status_code,200)
        self.assertEqual(self.client.get('/api/portfolio/services').json()['services'][0]['description'],'Updated public description')
    def test_csrf_required_for_login_registration_and_writes(self):
        c=Client(enforce_csrf_checks=True)
        self.assertEqual(self.post(c,'/api/auth/login/',{'email':self.a.email,'password':PASSWORD}).status_code,403)
        self.assertEqual(self.post(c,'/api/auth/register/',{}).status_code,403)
        token=c.get('/api/auth/session/').json()['csrfToken']
        r=c.post('/api/auth/login/',json.dumps({'email':self.a.email,'password':PASSWORD}),content_type='application/json',HTTP_X_CSRFTOKEN=token);self.assertEqual(r.status_code,200)
        self.assertEqual(self.post(c,'/api/client/profile/',{'full_name':'Changed'},'patch').status_code,403)
    def test_deactivated_client_session_denied(self):
        c=self.signed_in(self.a);self.a.is_active=False;self.a.save();self.assertEqual(c.get('/api/client/projects/').status_code,401)
    def test_password_change_requires_current_password(self):
        c=self.signed_in(self.a);r=self.post(c,'/api/auth/password/',{'current_password':'wrong','new_password':PASSWORD+'new','confirm_password':PASSWORD+'new'});self.assertEqual(r.status_code,400)
    def test_legacy_admin_hash_import(self):
        from lib.admin_backend import _password_hash
        u=User.objects.create(email='legacy@example.test',full_name='Legacy',role='ADMIN',is_staff=True,password='argon2'+_password_hash(PASSWORD))
        self.assertTrue(u.check_password(PASSWORD))
    def test_admin_without_mfa_marker_denied(self):
        c=Client();c.force_login(self.admin);self.assertEqual(c.get('/api/admin/clients/').status_code,403)
    def test_project_with_files_cannot_reassign_client(self):
        c=self.signed_in(self.admin);r=self.post(c,'/api/admin/projects/'+str(self.project.pk)+'/',{'client_id':self.b.pk},'patch');self.assertEqual(r.status_code,400)
    def test_backend_route_rewrite(self):
        r=self.client.get('/api/index?__path=/api/auth/session/');self.assertEqual(r.status_code,200);self.assertFalse(r.json()['authenticated'])
    def test_shared_pages_and_dashboard_render(self):
        for path in ['/login','/register','/password/reset']:
            self.assertEqual(self.client.get(path).status_code,200,path)
        for user,path in [(self.a,'/client/dashboard/'),(self.admin,'/dashboard/admin/')]:
            self.assertContains(self.signed_in(user).get(path),'workspace-nav')
    def test_browser_login_and_registration_redirect(self):
        result=self.client.post('/login',{'username':self.admin.email,'password':PASSWORD})
        self.assertRedirects(result,'/dashboard/admin/')
        c=Client();result=c.post('/register',{'full_name':'New Artist','email':'browser@example.test','phone':'123','password1':PASSWORD,'password2':PASSWORD})
        self.assertRedirects(result,'/client/dashboard/')
        self.assertEqual(User.objects.get(email='browser@example.test').role,'CLIENT')
    def test_native_admin_user_creation_form_uses_email(self):
        from django.contrib import admin
        from django.test import RequestFactory
        request=RequestFactory().get('/admin/studio/user/add/');request.user=self.admin
        form_class=admin.site._registry[User].get_form(request)
        form=form_class({'email':'managed@example.test','full_name':'Managed Admin','password1':PASSWORD,'password2':PASSWORD,'role':'ADMIN','is_staff':True})
        self.assertTrue(form.is_valid(),form.errors)
        user=form.save();self.assertTrue(user.check_password(PASSWORD));self.assertTrue(user.is_studio_admin)
    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_password_reset_delivery_and_single_use(self):
        from django.core import mail
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.http import urlsafe_base64_encode
        from django.utils.encoding import force_bytes
        result=self.client.post('/password/reset',{'email':self.a.email})
        self.assertEqual(result.status_code,200);self.assertEqual(len(mail.outbox),1)
        uid=urlsafe_base64_encode(force_bytes(self.a.pk));token=default_token_generator.make_token(self.a)
        url=reverse('password_reset_confirm',kwargs={'uid':uid,'token':token})
        self.assertIn(url,mail.outbox[0].body)
        result=self.client.post(url,{'new_password1':PASSWORD+'Changed','new_password2':PASSWORD+'Changed'})
        self.assertRedirects(result,'/login');self.a.refresh_from_db();self.assertTrue(self.a.check_password(PASSWORD+'Changed'))
        self.assertEqual(self.client.get(url).status_code,400)
    def test_client_cannot_mutate_any_admin_resource(self):
        c=self.signed_in(self.a)
        for resource in ['projects','enquiries','clients','services','portfolio','messages','files','testimonials','settings']:
            for method in ['post','patch','delete']:
                self.assertEqual(self.post(c,'/api/admin/'+resource+'/',{},method).status_code,403,(resource,method))
