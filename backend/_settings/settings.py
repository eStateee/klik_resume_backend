import os
from pathlib import Path
from datetime import timedelta

from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    """Читает булево значение из окружения ('True'/'1'/'yes' — истина)."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ('true', '1', 'yes', 'on')


def env_list(name, default=None):
    """Читает список значений из окружения (разделитель — запятая)."""
    raw = os.environ.get(name)
    if not raw:
        return list(default or [])
    return [item.strip() for item in raw.split(',') if item.strip()]


SECRET_KEY_ENV = os.environ.get('DJANGO_SECRET_KEY')
# По умолчанию DEBUG выключен: забытая переменная окружения на сервере не должна
# приводить к раскрытию трейсбеков и настроек.
DEBUG = env_bool('DEBUG', False)

if not SECRET_KEY_ENV and not DEBUG:
    raise RuntimeError("DJANGO_SECRET_KEY must be set in production (DEBUG=False).")
SECRET_KEY = SECRET_KEY_ENV or 'django-insecure-q&fidfi1f+vqdpfxo9ei!me!guhn*tz)8*4*&2n#wty07a7%^2'

# Хосты задаются через окружение; '*' остаётся только для локальной разработки.
ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS', ['*'] if DEBUG else [])
if not ALLOWED_HOSTS:
    raise RuntimeError(
        "DJANGO_ALLOWED_HOSTS must list the server hostnames when DEBUG=False."
    )

CSRF_TRUSTED_ORIGINS = env_list(
    'DJANGO_CSRF_TRUSTED_ORIGINS',
    ['http://localhost:8000', 'http://127.0.0.1:8000', 'https://*.ngrok-free.dev'],
)

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # Third-party apps
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    
    'drf_spectacular',
    'storages',
    'core',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = '_settings.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = '_settings.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('POSTGRES_DB', 'klik_db'),
        'USER': os.environ.get('POSTGRES_USER', 'postgres'),
        'PASSWORD': os.environ.get('POSTGRES_PASSWORD', 'postgres'),
        'HOST': os.environ.get('POSTGRES_HOST', 'localhost'),
        'PORT': os.environ.get('POSTGRES_PORT', '5432'),
    },
    'old_sqlite': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'core' / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'ru-ru'
TIME_ZONE = 'Europe/Minsk'
USE_I18N = True
USE_TZ = True

# Префиксы статики/медиа вынесены в окружение: на продакшене фронтенд (CRA)
# занимает /static/ своими бандлами, поэтому статика Django отдаётся с
# отдельного префикса (DJANGO_STATIC_URL=/django-static/). Значение должно
# совпадать с соответствующим location в конфиге nginx.
STATIC_URL = os.environ.get('DJANGO_STATIC_URL', 'static/')
STATIC_ROOT = BASE_DIR / 'static'
MEDIA_URL = os.environ.get('DJANGO_MEDIA_URL', 'media/')
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# CORS: полностью открытым остаётся только в DEBUG. На сервере перечисляем
# origin'ы фронтенда в DJANGO_CORS_ALLOWED_ORIGINS.
CORS_ALLOWED_ORIGINS = env_list('DJANGO_CORS_ALLOWED_ORIGINS')
CORS_ALLOW_ALL_ORIGINS = env_bool('DJANGO_CORS_ALLOW_ALL_ORIGINS', DEBUG)

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'core.authentication.CustomJWTAuthentication',
    ),
    # Закрыто по умолчанию: новый эндпоинт без явного permission_classes
    # не станет публичным по недосмотру.
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_THROTTLE_CLASSES': (
        'rest_framework.throttling.AnonRateThrottle',
    ),
    'DEFAULT_THROTTLE_RATES': {
        'anon': os.environ.get('THROTTLE_ANON', '120/min'),
        # Вход по одному номеру телефона без пароля — ограничиваем перебор номеров.
        'login': os.environ.get('THROTTLE_LOGIN', '10/min'),
        # Публичная отправка отзыва родителем.
        'review': os.environ.get('THROTTLE_REVIEW', '20/hour'),
    },
    # За nginx REMOTE_ADDR — это адрес прокси, поэтому клиента для троттлинга
    # определяем по последнему адресу в X-Forwarded-For.
    'NUM_PROXIES': int(os.environ.get('DJANGO_NUM_PROXIES', 1)),
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=int(os.environ.get('JWT_ACCESS_TOKEN_LIFETIME_MINUTES', 60))),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=int(os.environ.get('JWT_REFRESH_TOKEN_LIFETIME_DAYS', 1))),
}

# Безопасность транспорта. SECURE_SSL_REDIRECT/HSTS включаются отдельным флагом:
# на тестовом сервере без сертификата их включать нельзя.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_HTTPS = env_bool('DJANGO_USE_HTTPS', False)
SECURE_SSL_REDIRECT = USE_HTTPS
SESSION_COOKIE_SECURE = USE_HTTPS
CSRF_COOKIE_SECURE = USE_HTTPS
SESSION_COOKIE_HTTPONLY = True
SECURE_HSTS_SECONDS = 31536000 if USE_HTTPS else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = USE_HTTPS
SECURE_HSTS_PRELOAD = USE_HTTPS
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'

AUTHENTICATION_BACKENDS = [
    'core.auth_backends.PasswordlessAuthBackend',
    'django.contrib.auth.backends.ModelBackend',
]

# Redis Cache setup
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": os.environ.get('REDIS_URL', 'redis://localhost:6379/0'),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        }
    }
}

# Celery Configuration Options
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/1')
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_TIMEZONE = TIME_ZONE

CELERY_BEAT_SCHEDULE = {
    # Ночь с воскресенья на понедельник — актуализация доступов тьюторов к модулям
    # по их расписанию в AlfaCRM на предстоящую учебную неделю.
    'sync-all-tutors-access': {
        'task': 'core.tasks.sync_all_tutors_access',
        'schedule': crontab(minute=0, hour=0, day_of_week=1),
    },
    # Ежечасно — закрывает доступы, у которых истёк expires_at в середине недели.
    'revoke-expired-tutor-accesses': {
        'task': 'core.tasks.revoke_expired_accesses',
        'schedule': crontab(minute=0),
    },
}

CRM_API_URL = os.environ.get('CRM_API_URL', 'https://demo.alfacrm.pro')
CRM_EMAIL = os.environ.get('CRM_EMAIL', 'test@test.com')
CRM_API_KEY = os.environ.get('CRM_API_KEY', 'test_key')
CRM_TOKEN_CACHE_TIMEOUT = int(os.environ.get('CRM_TOKEN_CACHE_TIMEOUT', 3600))

# Сколько недель вперёд заглядывать при проверке расписания в CRM
# (за пределы ближайшей недели). Доступ к модулям выдаётся заранее.
CRM_LOOKAHEAD_WEEKS = int(os.environ.get('CRM_LOOKAHEAD_WEEKS', 2))

# Длина «дальнего» окна в неделях. Захватываем столько полных недель
# ПН–ВС после сдвига LOOKAHEAD_WEEKS.
CRM_WINDOW_WEEKS = int(os.environ.get('CRM_WINDOW_WEEKS', 2))

# Логирование: без явной конфигурации сообщения логгеров 'core' и 'app_resume'
# уходили в lastResort-обработчик и терялись всё, что ниже WARNING.
LOG_LEVEL = os.environ.get('DJANGO_LOG_LEVEL', 'INFO').upper()

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{asctime} {levelname} {name} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
        'core': {
            'handlers': ['console'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
        'app_resume': {
            'handlers': ['console'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
    },
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'KLik API',
    'DESCRIPTION': 'KLik API',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'COMPONENT_SPLIT_REQUEST': True,
}

# S3 Storage Settings (hoster.by)
AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
AWS_STORAGE_BUCKET_NAME = os.environ.get('AWS_STORAGE_BUCKET_NAME', 'storage1022')
AWS_S3_ENDPOINT_URL = os.environ.get('AWS_S3_ENDPOINT_URL', 'https://storage-1022.s3hoster.by')
AWS_S3_REGION_NAME = os.environ.get('AWS_S3_REGION_NAME', 'us-east-1')
AWS_DEFAULT_ACL = 'private'
AWS_QUERYSTRING_AUTH = True
AWS_S3_SIGNATURE_VERSION = 's3v4'
AWS_S3_ADDRESSING_STYLE = os.environ.get('AWS_S3_ADDRESSING_STYLE', 'path')

if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
            "OPTIONS": {
                "access_key": AWS_ACCESS_KEY_ID,
                "secret_key": AWS_SECRET_ACCESS_KEY,
                "bucket_name": AWS_STORAGE_BUCKET_NAME,
                "endpoint_url": AWS_S3_ENDPOINT_URL,
                "region_name": AWS_S3_REGION_NAME,
                "signature_version": AWS_S3_SIGNATURE_VERSION,
                "addressing_style": AWS_S3_ADDRESSING_STYLE,
                "default_acl": AWS_DEFAULT_ACL,
                "querystring_auth": AWS_QUERYSTRING_AUTH,
            },
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
