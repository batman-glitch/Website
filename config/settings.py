import os
from pathlib import Path
import dj_database_url
BASE_DIR = Path(__file__).resolve().parent.parent
PRODUCTION = bool(os.environ.get('VERCEL'))
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY') or os.environ.get('ADMIN_SESSION_SECRET')
if not SECRET_KEY:
    if PRODUCTION:
        raise RuntimeError('Set DJANGO_SECRET_KEY before deployment.')
    SECRET_KEY = 'local-development-only-change-before-production-2026'
DEBUG = not PRODUCTION and os.environ.get('DJANGO_DEBUG') == '1'
ALLOWED_HOSTS = ['localhost', '127.0.0.1', 'testserver', '.vercel.app'] + [x for x in os.environ.get('DJANGO_ALLOWED_HOSTS', '').split(',') if x]
INSTALLED_APPS = ['django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes', 'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles', 'studio']
MIDDLEWARE = ['studio.middleware.VercelPathMiddleware', 'django.middleware.security.SecurityMiddleware', 'django.contrib.sessions.middleware.SessionMiddleware', 'django.middleware.common.CommonMiddleware', 'django.middleware.csrf.CsrfViewMiddleware', 'django.contrib.auth.middleware.AuthenticationMiddleware', 'studio.middleware.AccountSecurityMiddleware', 'django.contrib.messages.middleware.MessageMiddleware', 'django.middleware.clickjacking.XFrameOptionsMiddleware']
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND':'django.template.backends.django.DjangoTemplates','DIRS':[BASE_DIR/'templates'],'APP_DIRS':True,'OPTIONS':{'context_processors':['django.template.context_processors.request','django.contrib.auth.context_processors.auth','django.contrib.messages.context_processors.messages']}}]
WSGI_APPLICATION = 'config.wsgi.app'
DATABASES = {'default': dj_database_url.parse(os.environ['DATABASE_URL'], conn_max_age=0, ssl_require=PRODUCTION) if os.environ.get('DATABASE_URL') else {'ENGINE':'django.db.backends.sqlite3','NAME':os.environ.get('LOCAL_DATABASE_PATH', str(BASE_DIR/'development.sqlite3'))}}
if PRODUCTION and not os.environ.get('DATABASE_URL'):
    raise RuntimeError('Production requires PostgreSQL DATABASE_URL.')
AUTH_USER_MODEL = 'studio.User'
AUTH_PASSWORD_VALIDATORS = [{'NAME':'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},{'NAME':'django.contrib.auth.password_validation.MinimumLengthValidator','OPTIONS':{'min_length':14}},{'NAME':'django.contrib.auth.password_validation.CommonPasswordValidator'},{'NAME':'django.contrib.auth.password_validation.NumericPasswordValidator'}]
PASSWORD_HASHERS = ['django.contrib.auth.hashers.Argon2PasswordHasher', 'django.contrib.auth.hashers.PBKDF2PasswordHasher', 'studio.hashers.LegacyPasswordHasher']
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
STATIC_URL = '/django-static/'
STATIC_ROOT = BASE_DIR/'public'/'django-static'
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_COOKIE_NAME = '__Host-blessson-session' if PRODUCTION else 'blessson_session'
CSRF_COOKIE_NAME = '__Host-blessson-csrf' if PRODUCTION else 'blessson_csrf'
SESSION_COOKIE_SECURE = PRODUCTION
CSRF_COOKIE_SECURE = PRODUCTION
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = 4*60*60
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO','https')
SECURE_SSL_REDIRECT = PRODUCTION
SECURE_HSTS_SECONDS = 31536000 if PRODUCTION else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = PRODUCTION
X_FRAME_OPTIONS = 'DENY'
LOGIN_URL = '/login'
PASSWORD_RESET_TIMEOUT = 3600
DATA_UPLOAD_MAX_MEMORY_SIZE = 4*1024*1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 3*1024*1024
CSRF_FAILURE_VIEW = 'studio.views.csrf_failure'
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend' if os.environ.get('EMAIL_HOST') else ('studio.mail.ResendBackend' if os.environ.get('RESEND_API_KEY') else 'django.core.mail.backends.locmem.EmailBackend')
EMAIL_HOST = os.environ.get('EMAIL_HOST','')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT','587'))
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER','')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD','')
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS','1') == '1'
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL','Blessson Studio <noreply@example.invalid>')
EMAIL_READY = bool(os.environ.get('EMAIL_HOST') or os.environ.get('RESEND_API_KEY'))
