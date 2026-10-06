import uuid
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.db.models.functions import Lower
class UserManager(BaseUserManager):
    def create_user(self,email,password=None,**extra):
        if not email: raise ValueError('Email is required.')
        if extra.get('role')=='ADMIN':extra.setdefault('is_staff',True)
        user=self.model(email=self.normalize_email(email).lower(),**extra)
        user.set_password(password)
        user.save(using=self._db)
        return user
    def create_superuser(self,email,password=None,**extra):
        extra.update(role='ADMIN',is_staff=True,is_superuser=True)
        return self.create_user(email,password,**extra)
class User(AbstractUser):
    username=None
    email=models.EmailField(unique=True)
    full_name=models.CharField(max_length=120)
    phone=models.CharField(max_length=30,blank=True)
    role=models.CharField(max_length=6,choices=[('CLIENT','Client'),('ADMIN','Administrator')],default='CLIENT')
    legacy_admin_id=models.PositiveBigIntegerField(null=True,blank=True,unique=True)
    mfa_enabled=models.BooleanField(default=False)
    totp_secret_enc=models.TextField(blank=True)
    must_change_password=models.BooleanField(default=False)
    USERNAME_FIELD='email'
    REQUIRED_FIELDS=['full_name']
    objects=UserManager()
    class Meta:
        constraints=[models.UniqueConstraint(Lower('email'),name='studio_email_case_unique'),models.CheckConstraint(condition=models.Q(role='ADMIN',is_staff=True)|models.Q(role='CLIENT',is_staff=False,is_superuser=False),name='studio_role_privileges_valid')]
    @property
    def is_studio_admin(self): return self.is_active and self.role=='ADMIN' and self.is_staff
class Service(models.Model):
    name=models.CharField(max_length=60,unique=True)
    title=models.CharField(max_length=100)
    description=models.TextField(blank=True,max_length=1000)
    price=models.DecimalField(max_digits=10,decimal_places=2,null=True,blank=True)
    active=models.BooleanField(default=True)
    display_order=models.IntegerField(default=0)
    updated_at=models.DateTimeField(auto_now=True)
    def __str__(self): return self.name
class Project(models.Model):
    STATUSES=[(s,s.replace('_',' ').title()) for s in ['enquiry','accepted','in_progress','review','revision','completed','cancelled']]
    client=models.ForeignKey(User,on_delete=models.PROTECT,related_name='projects',limit_choices_to={'role':'CLIENT'})
    name=models.CharField(max_length=160)
    service=models.ForeignKey(Service,on_delete=models.PROTECT)
    description=models.TextField(blank=True,max_length=4000)
    status=models.CharField(max_length=20,choices=STATUSES,default='enquiry')
    start_date=models.DateField(null=True,blank=True)
    expected_completion=models.DateField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
class Enquiry(models.Model):
    client=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True,related_name='enquiries')
    name=models.CharField(max_length=120)
    email=models.EmailField()
    project_name=models.CharField(max_length=160,blank=True)
    service=models.CharField(max_length=60)
    message=models.TextField(max_length=4000)
    timeline=models.CharField(max_length=80,blank=True)
    genre=models.CharField(max_length=100,blank=True)
    status=models.CharField(max_length=20,choices=[(s,s.replace('_',' ').title()) for s in ['new','accepted','rejected','in_progress','completed']],default='new')
    response=models.TextField(blank=True,max_length=4000)
    internal_notes=models.TextField(blank=True,max_length=4000)
    project=models.OneToOneField(Project,on_delete=models.SET_NULL,null=True,blank=True)
    legacy_id=models.PositiveBigIntegerField(unique=True,null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
class ProjectFile(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    project=models.ForeignKey(Project,on_delete=models.CASCADE,related_name='files')
    uploaded_by=models.ForeignKey(User,on_delete=models.PROTECT)
    name=models.CharField(max_length=160)
    content_type=models.CharField(max_length=100)
    size=models.PositiveIntegerField()
    encrypted_content=models.BinaryField(null=True)
    blob_url=models.URLField(max_length=1200,blank=True)
    status=models.CharField(max_length=12,default='ready',choices=[('pending','Pending'),('ready','Ready')])
    created_at=models.DateTimeField(auto_now_add=True)
class Message(models.Model):
    client=models.ForeignKey(User,on_delete=models.CASCADE,related_name='conversation')
    sender=models.ForeignKey(User,on_delete=models.PROTECT,related_name='sent_messages')
    project=models.ForeignKey(Project,on_delete=models.SET_NULL,null=True,blank=True)
    body=models.TextField(max_length=4000)
    created_at=models.DateTimeField(auto_now_add=True)
class PortfolioWork(models.Model):
    legacy_id=models.PositiveBigIntegerField(unique=True,null=True,blank=True)
    title=models.CharField(max_length=120)
    artist=models.CharField(max_length=120,blank=True)
    service=models.CharField(max_length=60)
    genre=models.CharField(max_length=100,blank=True)
    release_year=models.PositiveIntegerField(null=True,blank=True)
    description=models.TextField(blank=True,max_length=4000)
    cover_url=models.CharField(max_length=1200,blank=True)
    audio_url=models.CharField(max_length=1200,blank=True)
    audio_label=models.CharField(max_length=120,blank=True)
    is_published=models.BooleanField(default=False)
    is_featured=models.BooleanField(default=False)
    display_order=models.IntegerField(default=0)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
class SiteSetting(models.Model):
    key=models.CharField(max_length=80,primary_key=True)
    value=models.TextField(max_length=1200)
class Testimonial(models.Model):
    client=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True)
    name=models.CharField(max_length=120)
    quote=models.TextField(max_length=1200)
    published=models.BooleanField(default=False)
    created_at=models.DateTimeField(auto_now_add=True)
class Activity(models.Model):
    client=models.ForeignKey(User,on_delete=models.CASCADE,null=True,blank=True)
    actor=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True,related_name='actions')
    description=models.CharField(max_length=240)
    created_at=models.DateTimeField(auto_now_add=True)
class Throttle(models.Model):
    key=models.CharField(max_length=64,primary_key=True)
    count=models.PositiveIntegerField(default=0)
    starts=models.DateTimeField()
class ImportState(models.Model):
    key=models.CharField(max_length=80,primary_key=True)
    completed_at=models.DateTimeField(auto_now_add=True)
