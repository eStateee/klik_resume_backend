import requests
from typing import Optional, Dict, Any
from django.conf import settings
from django.core.cache import cache
import logging

logger = logging.getLogger("app_resume")

BASE_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept": "application/json, text/plain, */*",
}


def login_to_alfa_crm() -> Optional[str]:
    """
    Авторизация в CRM и получение токена.
    """
    cached_token = cache.get("crm_auth_token")
    if cached_token:
        return cached_token

    if not getattr(settings, 'CRM_API_URL', None) or not getattr(settings, 'CRM_EMAIL', None) or not getattr(settings, 'CRM_API_KEY', None):
        return None

    data = {"email": settings.CRM_EMAIL, "api_key": settings.CRM_API_KEY}
    base_url = settings.CRM_API_URL.rstrip("/")
    url = f"{base_url}/v2api/auth/login"

    try:
        response = requests.post(url, headers=BASE_HEADERS, json=data, timeout=30)

        if response.status_code == 200:
            token_data = response.json()
            token = token_data.get("token")

            # Сохраняем токен в кэше Redis на 1 час (3600 секунд) через django-redis
            if token:
                cache.set("crm_auth_token", token, 3600)
            return token
        else:
            return None
    except requests.exceptions.Timeout:
        logger.error("CRM login request timed out")
        return None
    except requests.exceptions.ConnectionError:
        logger.error("CRM login connection error")
        return None
    except Exception as e:
        logger.error(f"Error during CRM login: {str(e)}")
        return None


def make_authenticated_request(url: str, headers: dict, data: dict = None, params: dict = None):
    """
    Выполняет аутентифицированный запрос к CRM с автоматическим обновлением токена при необходимости
    """
    headers = {**headers}

    try:
        response = requests.post(url, headers=headers, json=data, params=params, timeout=30)
    except requests.exceptions.Timeout:
        logger.error("CRM request timed out")
        raise
    except requests.exceptions.ConnectionError:
        logger.error("CRM request connection error")
        raise

    if response.status_code == 401:
        logger.warning("Received 401 error, refreshing token...")
        clear_crm_auth_token()
        new_token = login_to_alfa_crm()
        if not new_token:
            logger.error("Failed to refresh token after 401 error")
            return response

        headers["X-ALFACRM-TOKEN"] = new_token
        try:
            response = requests.post(url, headers=headers, json=data, params=params, timeout=30)
        except requests.exceptions.Timeout:
            logger.error("CRM request timed out on retry")
            raise
        except requests.exceptions.ConnectionError:
            logger.error("CRM request connection error on retry")
            raise

    return response


def clear_crm_auth_token():
    """
    Удаляет токен аутентификации CRM из кэша
    """
    cache.delete("crm_auth_token")

# Остальные методы (get_tutor_data_from_crm, get_client_data_from_crm, etc.)
# остаются аналогичными, просто используют новые функции login_to_alfa_crm()
