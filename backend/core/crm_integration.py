import requests
import redis
from typing import Optional, Dict, Any
from django.conf import settings
from app_resumes.models import TutorProfile
import logging

logger = logging.getLogger("app_resume")

# Redis connection
redis_client = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB, decode_responses=True)


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
    # Попробуем получить токен из Redis
    cached_token = redis_client.get("crm_auth_token")
    if cached_token:
        return cached_token

    if not settings.CRM_API_URL or not settings.CRM_EMAIL or not settings.CRM_API_KEY:
        return None

    data = {"email": settings.CRM_EMAIL, "api_key": settings.CRM_API_KEY}
    # Remove the "https://" prefix and any trailing slashes to construct the proper URL
    base_url = settings.CRM_API_URL.rstrip("/")
    url = f"{base_url}/v2api/auth/login"

    try:
        response = requests.post(url, headers=BASE_HEADERS, json=data, timeout=30)

        if response.status_code == 200:
            token_data = response.json()
            token = token_data.get("token")

            # Сохраняем токен в Redis на 1 час (3600 секунд)
            if token:
                redis_client.setex("crm_auth_token", 3600, token)
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

    # Если получили ошибку 401, пробуем обновить токен и повторить запрос
    if response.status_code == 401:
        logger.warning("Received 401 error, refreshing token...")
        clear_crm_auth_token()  # Очищаем просроченный токен
        new_token = login_to_alfa_crm()  # Получаем новый токен
        if not new_token:
            logger.error("Failed to refresh token after 401 error")
            return response  # Возвращаем оригинальный ответ с ошибкой 401

        # Обновляем заголовки с новым токеном
        headers["X-ALFACRM-TOKEN"] = new_token
        try:
            response = requests.post(url, headers=headers, json=data, params=params, timeout=30)  # Повторяем запрос
        except requests.exceptions.Timeout:
            logger.error("CRM request timed out on retry")
            raise
        except requests.exceptions.ConnectionError:
            logger.error("CRM request connection error on retry")
            raise

    return response


def clear_crm_auth_token():
    """
    Удаляет токен аутентификации CRM из Redis
    """
    redis_client.delete("crm_auth_token")


def get_tutor_data_from_crm(phone: str, branch: str = None) -> Optional[Dict[str, Any]]:
    """
    Get tutor data from external CRM system using the old get_teacher logic
    """
    logger.info(f"Получение данных преподавателя по телефону: {phone}, филиал: {branch}")

    if not branch or not settings.CRM_API_KEY:
        logger.error("Отсутствует филиал или API ключ CRM")
        return None

    # Get token for authentication
    token = login_to_alfa_crm()
    if not token:
        logger.error("Не удалось получить токен аутентификации")
        return None

    # Use the branch from tutor profile to construct the URL
    url = f"{settings.CRM_API_URL}/v2api/{branch}/teacher/index"
    data = {"phone": phone}  # Using ID instead of phone as in the original example

    headers = {**BASE_HEADERS, "X-ALFACRM-TOKEN": token}

    try:
        logger.debug(f"Отправка запроса к CRM: {url}")
        response = make_authenticated_request(url, headers, data)
        response.raise_for_status()
        result = response.json()

        items = result.get("items", [])
        if items:
            logger.info(f"Получены данные преподавателя для телефона {phone}")
            return items[0]
        else:
            logger.info(f"Преподаватель с телефоном {phone} не найден")
        return None
    except requests.HTTPError as e:
        logger.error(f"HTTP ошибка при получении данных преподавателя: {str(e)}")
        return None
    except requests.RequestException as e:
        logger.error(f"Ошибка запроса при получении данных преподавателя: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Неизвестная ошибка при получении данных преподавателя: {str(e)}")
        return None


def get_client_data_from_crm(student_crm_id: str, branch: str = None) -> Optional[Dict[str, Any]]:
    """
    Get client data from external CRM system using the old find_client_by_id logic
    """
    logger.info(f"Получение данных клиента по ID: {student_crm_id}, филиал: {branch}")

    if not branch or not settings.CRM_API_KEY:
        logger.error("Отсутствует филиал или API ключ CRM")
        return None

    # Get token for authentication
    token = login_to_alfa_crm()
    if not token:
        logger.error("Не удалось получить токен аутентификации")
        return None

    # Use the branch from tutor profile to construct the URL
    url = f"{settings.CRM_API_URL}/v2api/{branch}/customer/index"
    # Using the logic from find_client_by_id function
    data = {"id": student_crm_id, "is_study": 2, "page": 0}  # 1 - clients, 0 - leads, 2 - all

    headers = {**BASE_HEADERS, "X-ALFACRM-TOKEN": token}

    try:
        logger.debug(f"Отправка запроса к CRM: {url}")
        response = make_authenticated_request(url, headers, data)
        response.raise_for_status()
        result = response.json()

        # Check if response has items
        clients = result.get("items", [])

        if not clients:
            logger.info(f"Клиент с ID {student_crm_id} не найден")
            return None

        if len(clients) > 1:
            logger.warning(f"Найдено несколько клиентов с ID {student_crm_id}, возвращаем первого")
            # Return the first client if multiple found
            pass

        logger.info(f"Получены данные клиента для ID {student_crm_id}")
        return clients[0]
    except requests.HTTPError as e:
        logger.error(f"HTTP ошибка при получении данных клиента: {str(e)}")
        return None
    except requests.RequestException as e:
        logger.error(f"Ошибка запроса при получении данных клиента: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Неизвестная ошибка при получении данных клиента: {str(e)}")
        return None


def get_tutor_groups_from_crm(tutor_crm_id: str, branch: str = None) -> Optional[Dict[str, Any]]:
    """
    Get tutor groups from external CRM system using the old get_teacher_groups logic
    """
    logger.info(f"Получение групп преподавателя с ID: {tutor_crm_id}, филиал: {branch}")

    if not branch or not settings.CRM_API_KEY:
        logger.error("Отсутствует филиал или API ключ CRM")
        return None

    # Get token for authentication
    token = login_to_alfa_crm()
    if not token:
        logger.error("Не удалось получить токен аутентификации")
        return None

    url = f"{settings.CRM_API_URL}/v2api/{branch}/group/index"
    data = {"teacher_id": tutor_crm_id}

    headers = {**BASE_HEADERS, "X-ALFACRM-TOKEN": token}

    try:
        logger.debug(f"Отправка запроса к CRM: {url}")
        response = make_authenticated_request(url, headers, data)
        response.raise_for_status()
        result = response.json()

        all_groups = result.get("items", [])
        if all_groups:
            teacher_id_int = int(tutor_crm_id) if tutor_crm_id.isdigit() else tutor_crm_id
            filtered_groups = []
            for group in all_groups:
                # Check if the teacher is in this group by looking at the teachers list
                teachers = group.get("teachers", [])
                if any(teacher.get("id") == teacher_id_int for teacher in teachers):
                    filtered_groups.append(group)

            logger.info(f"Найдено {len(filtered_groups)} групп для преподавателя {tutor_crm_id}")
            return filtered_groups
        else:
            logger.info(f"Группы для преподавателя {tutor_crm_id} не найдены")
        return None
    except requests.HTTPError as e:
        logger.error(f"HTTP ошибка при получении групп преподавателя: {str(e)}")
        return None
    except requests.RequestException as e:
        logger.error(f"Ошибка запроса при получении групп преподавателя: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Неизвестная ошибка при получении групп преподавателя: {str(e)}")
        return None


def get_group_clients_from_crm(group_id: str, branch: str = None) -> Optional[Dict[str, Any]]:
    """
    Get clients in a group from external CRM system using the old get_clients_in_group logic
    """
    logger.info(f"Получение клиентов группы с ID: {group_id}, филиал: {branch}")

    if not branch or not settings.CRM_API_KEY:
        logger.error("Отсутствует филиал или API ключ CRM")
        return None

    # Get token for authentication
    token = login_to_alfa_crm()
    if not token:
        logger.error("Не удалось получить токен аутентификации")
        return None

    url = f"{settings.CRM_API_URL}/v2api/{branch}/cgi/index"
    params = {"group_id": group_id}

    headers = {**BASE_HEADERS, "X-ALFACRM-TOKEN": token}

    try:
        logger.debug(f"Отправка запроса к CRM: {url}")
        response = make_authenticated_request(url, headers, None, params)
        response.raise_for_status()
        result = response.json()

        customer_ids = [customer_id["customer_id"] for customer_id in result.get("items", [])]

        # For each customer_id, get client data
        clients_data = []
        for customer_id in customer_ids:
            # Note: This is recursive and might need to be optimized
            client_data = get_client_data_from_crm(str(customer_id), branch)
            if client_data:
                client_name = client_data.get("name", "Неизвестный клиент")
                study_start_date = client_data.get("custom_datano")  # Дата начала обучения из CRM
            else:
                client_name = "Клиент не найден"
                study_start_date = None
            clients_data.append((customer_id, client_name, study_start_date))

        # Create the response format
        clients_in_group = [
            {"customer_id": customer_id, "client_name": client_name, "custom_datano": study_start_date}
            for customer_id, client_name, study_start_date in clients_data
        ]
        logger.info(f"Получено {len(clients_in_group)} клиентов для группы {group_id}")
        return clients_in_group
    except requests.HTTPError as e:
        logger.error(f"HTTP ошибка при получении клиентов группы: {str(e)}")
        return None
    except requests.RequestException as e:
        logger.error(f"Ошибка запроса при получении клиентов группы: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Неизвестная ошибка при получении клиентов группы: {str(e)}")
        return None


def get_all_groups() -> Optional[Dict[str, Any]]:
    """
    Get all groups from external CRM system
    """
    logger.info("Получение всех групп из CRM")

    if not settings.CRM_API_KEY:
        logger.error("Отсутствует API ключ CRM")
        return None

    # Get token for authentication
    token = login_to_alfa_crm()
    if not token:
        logger.error("Не удалось получить токен аутентификации")
        return None

    all_items = []
    branches = [1, 2, 3, 4]

    headers = {**BASE_HEADERS, "X-ALFACRM-TOKEN": token}

    for branch in branches:
        page = 0

        while True:
            # Construct the URL for the current branch and page
            url = f"{settings.CRM_API_URL}/v2api/{branch}/group/index"
            data = {"page": page, "limit": 50}  # Assuming API supports pagination

            try:
                logger.debug(f"Отправка запроса к CRM: {url}")
                response = make_authenticated_request(url, headers, data)
                response.raise_for_status()
                result = response.json()

                items = result.get("items", [])
                current_page_count = len(items)
                total = result.get("total", 0)

                if current_page_count == 0:
                    logger.info(f"Нет больше данных для филиала {branch}, страница {page}")
                    break  # No more data

                all_items.extend(items)
                page += 1
                logger.debug(f"Получено {current_page_count} групп для филиала {branch}, страница {page}")

                # Additional protection: if we've collected all records
                if len(all_items) >= total > 0:
                    logger.info(f"Получены все {total} групп для филиала {branch}")
                    break

            except requests.HTTPError as e:
                logger.error(f"HTTP ошибка при получении групп для филиала {branch}: {str(e)}")
                break
            except requests.RequestException as e:
                logger.error(f"Ошибка запроса при получении групп для филиала {branch}: {str(e)}")
                break
            except Exception as e:
                logger.error(f"Неизвестная ошибка при получении групп для филиала {branch}: {str(e)}")
                break

    logger.info(f"Всего получено {len(all_items)} групп из всех филиалов")
    return all_items
