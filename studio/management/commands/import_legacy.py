import base64
from datetime import datetime
from django.core.management.base import BaseCommand
from django.db import connection,transaction
from django.utils import timezone
from studio.models import User,Service,Enquiry,PortfolioWork,SiteSetting,ImportState
from lib.platform_backend import DEFAULT_SETTINGS,SERVICE_SEEDS
class Command(BaseCommand):
    help='Import legacy portfolio content and trusted admin accounts once, without changing legacy tables.'
    def handle(self,*args,**options):
        if ImportState.objects.filter(pk='legacy-v1').exists():self.stdout.write('Legacy import already complete.');return
        tables=set(connection.introspection.table_names())
        def rows(table):
            if table not in tables:return []
            with connection.cursor() as cursor:
                cursor.execute('SELECT * FROM '+table)
                names=[d[0] for d in cursor.description]
                return [dict(zip(names,r)) for r in cursor.fetchall()]
        with transaction.atomic():
            for row in rows('admin_users'):
                encoded=row['password_hash']
                password='argon2'+encoded if encoded.startswith('$argon2id$') else 'legacy_portfolio$'+base64.b64encode(encoded.encode()).decode()
                imported, created = User.objects.get_or_create(email=row['email'].strip().lower(),defaults={'full_name':'Blessson','password':password,'role':'ADMIN','is_staff':True,'is_superuser':True,'legacy_admin_id':row['id'],'mfa_enabled':bool(row.get('mfa_enabled')),'totp_secret_enc':row.get('totp_secret_enc') or '','must_change_password':bool(row.get('must_change_password'))})
                if created and row.get('created_at'):User.objects.filter(pk=imported.pk).update(date_joined=row['created_at'])
            services=rows('portfolio_services')
            for row in services:
                Service.objects.get_or_create(name=row['name'],defaults={k:row[k] for k in ['title','description','active','display_order']})
            if not services:
                for index,(name,title,description) in enumerate(SERVICE_SEEDS):Service.objects.get_or_create(name=name,defaults={'title':title,'description':description,'display_order':index*10})
            for row in rows('portfolio_projects'):
                fields={k:row[k] for k in ['title','artist','service','genre','release_year','description','cover_url','audio_url','audio_label','is_published','is_featured','display_order']}
                imported, created = PortfolioWork.objects.get_or_create(legacy_id=row['id'],defaults=fields)
                if created:PortfolioWork.objects.filter(pk=imported.pk).update(created_at=row['created_at'],updated_at=row['updated_at'])
            for row in rows('inquiries'):
                # Guest enquiries are never assigned by email alone.
                fields={k:row[k] for k in ['name','email','service','message','timeline','genre','status']}
                fields['project_name']=row.get('project','')
                imported, created = Enquiry.objects.get_or_create(legacy_id=row['id'],defaults=fields)
                if created:Enquiry.objects.filter(pk=imported.pk).update(created_at=row['created_at'])
            for key,value in DEFAULT_SETTINGS.items():SiteSetting.objects.get_or_create(key=key,defaults={'value':value})
            for row in rows('portfolio_settings'):SiteSetting.objects.update_or_create(key=row['setting_key'],defaults={'value':row['setting_value']})
            ImportState.objects.get_or_create(key='legacy-v1')
        self.stdout.write(self.style.SUCCESS('Imported legacy content and trusted admin accounts.'))
