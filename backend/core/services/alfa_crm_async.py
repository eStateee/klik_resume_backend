"""

Задача
------
По ``crm_id`` наставника (педагога в AlfaCRM) получить список идентификаторов
предметов, по которым у него есть уроки на ближайшую учебную неделю (ПН–ВС).
Полученный список используется системой выдачи доступов к учебным модулям
(см. ``core.tasks.sync_all_tutors_access``).

Алгоритм
--------------------
    Наставник (crm_id)
        -> Группы наставника                (group/index, teacher_id=crm_id)
        -> Уроки этих групп на неделю ПН–ВС  (lesson/index, group_id + date_from/date_to)
        -> Предмет каждого урока             (lesson.subject_id)
        -> [subject_ids]                     (уникальные, отсортированные)

Дополнительно (опционально, ``include_personal_lessons=True``) собираются уроки,
где наставник указан непосредственно педагогом урока (``lesson.teacher_id``), —
это покрывает индивидуальные уроки, не привязанные ни к одной группе.

Запуск
------
Вызывается из еженедельной Celery-таски (ночь с воскресенья на понедельник) и
проверяет уроки наступающей недели ПН–ВС. Логика выбора недели — см.
:func:`get_week_range`.

Токен авторизации AlfaCRM кешируется в общем Django cache (Redis) под тем же
ключом, что и синхронный клиент в ``core.crm_integration`` — это исключает
взаимную инвалидацию токена между синхронным и асинхронным клиентами.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Iterable, Sequence
from datetime import date, timedelta
from typing import Any, Final

import aiohttp
from django.conf import settings
from django.core.cache import cache

__all__ = [
    "AlfaCRMClient",
    "AlfaCRMError",
    "RateLimiter",
    "collect_group_ids",
    "extract_subject_ids",
    "fetch_group_lessons",
    "fetch_personal_lessons",
    "fetch_tutor_groups",
    "get_tutor_subject_ids",
    "get_week_range",
    "resolve_subject_names",
]

logger = logging.getLogger("app_resume")

# --------------------------------------------------------------------------- #
# Конфигурация                                                                 #
# --------------------------------------------------------------------------- #

#: Ключ кеша токена авторизации — общий с core.crm_integration.login_to_alfa_crm.
CRM_TOKEN_CACHE_KEY: Final[str] = "crm_auth_token"

#: Филиалы компании по умолчанию — используется, если вызывающий код не передал
#: свой список (см. также core.crm_integration.get_all_groups).
BRANCH_IDS: Final[tuple[int, ...]] = (1, 2, 3, 4)

#: Лимит API: не более 5 запросов в секунду на любые методы.
REQUESTS_PER_SECOND: Final[int] = 5

#: Статусы уроков: 1 — запланированный, 2 — отменённый, 3 — проведённый.
#: Для будущей недели интересны запланированные; проведённые добавлены на случай
#: ручного/повторного запуска в середине недели, когда часть уроков уже прошла.
LESSON_STATUS_PLANNED: Final[int] = 1
LESSON_STATUS_DONE: Final[int] = 3
DEFAULT_LESSON_STATUSES: Final[tuple[int, ...]] = (
    LESSON_STATUS_PLANNED,
    LESSON_STATUS_DONE,
)

#: Формат дат для фильтров lesson/index — "YYYY-MM-DD".
API_DATE_FORMAT: Final[str] = "%Y-%m-%d"

#: Защита от бесконечного цикла пейджинации.
MAX_PAGES: Final[int] = 200

#: Сетевые настройки и ретраи.
REQUEST_TIMEOUT: Final[float] = 30.0
MAX_RETRIES: Final[int] = 3
RETRY_BACKOFF: Final[float] = 1.5


class AlfaCRMError(RuntimeError):
    """Ошибка обращения к API AlfaCRM (HTTP 4XX/5XX или некорректный ответ)."""


# --------------------------------------------------------------------------- #
# Работа с датами                                                              #
# --------------------------------------------------------------------------- #


def get_week_range(today: date | None = None) -> tuple[date, date]:
    """Вернуть границы учебной недели ПН–ВС, которую нужно проверить.

    Синхронизация запускается ночью с воскресенья на понедельник, поэтому
    возможны два варианта момента запуска:

    * запуск в **воскресенье** (например, 23:50) — нужна *следующая* неделя,
      то есть понедельник = завтра;
    * запуск в **понедельник** (например, 00:30) — нужна *текущая* неделя,
      то есть понедельник = сегодня.

    Для устойчивости при ручном запуске в любой другой день недели возвращается
    текущая неделя (понедельник этой недели — воскресенье этой недели).

    Args:
        today: Дата, от которой считать неделю. По умолчанию — сегодня.

    Returns:
        Кортеж ``(monday, sunday)`` — включительные границы недели.
    """
    today = today or date.today()

    if today.weekday() == 6:  # 6 == воскресенье: целевая неделя начинается завтра
        monday = today + timedelta(days=1)
    else:  # ПН..СБ: берём понедельник текущей недели
        monday = today - timedelta(days=today.weekday())

    sunday = monday + timedelta(days=6)
    return monday, sunday


def format_api_date(value: date) -> str:
    """Привести дату к формату фильтров AlfaCRM (``YYYY-MM-DD``)."""
    return value.strftime(API_DATE_FORMAT)


# --------------------------------------------------------------------------- #
# Ограничитель частоты запросов                                                #
# --------------------------------------------------------------------------- #


class RateLimiter:
    """Асинхронный ограничитель частоты запросов (скользящее окно).

    AlfaCRM разрешает не более 5 обращений в секунду, а мы шлём запросы
    конкурентно, поэтому каждый вызов API проходит через этот ограничитель.

    Args:
        rate: Максимальное число операций за период.
        period: Длина окна в секундах.
    """

    def __init__(self, rate: int = REQUESTS_PER_SECOND, period: float = 1.0) -> None:
        self._rate = rate
        self._period = period
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Дождаться свободного слота и занять его."""
        while True:
            async with self._lock:
                now = time.monotonic()
                # Выбрасываем отметки, вышедшие за пределы окна.
                while self._calls and now - self._calls[0] >= self._period:
                    self._calls.popleft()

                if len(self._calls) < self._rate:
                    self._calls.append(now)
                    return

                # Слот освободится, когда самая старая отметка покинет окно.
                sleep_for = self._period - (now - self._calls[0])

            await asyncio.sleep(max(sleep_for, 0.001))


# --------------------------------------------------------------------------- #
# Клиент AlfaCRM                                                               #
# --------------------------------------------------------------------------- #


class AlfaCRMClient:
    """Асинхронный клиент AlfaCRM v2api поверх ``aiohttp``.

    Берёт на себя авторизацию и кеширование токена, лимит 5 запросов/сек,
    ретраи и пейджинацию ``index``-методов. Токен кешируется в общем Django
    cache (Redis), под тем же ключом, что и синхронный клиент в
    ``core.crm_integration`` — оба клиента переиспользуют один и тот же токен.

    Использовать как асинхронный контекстный менеджер::

        async with AlfaCRMClient() as client:
            groups = await client.fetch_all("group", {"teacher_id": 1}, branch=1)

    Args:
        host: Базовый URL CRM. По умолчанию — ``settings.CRM_API_URL``.
        credentials: Словарь с ключами ``email`` и ``api_key``. По умолчанию —
            ``settings.CRM_EMAIL`` / ``settings.CRM_API_KEY``.
        rate_limiter: Ограничитель частоты (по умолчанию 5 запросов/сек).
        session: Готовая сессия ``aiohttp`` (если нужно переиспользовать внешнюю).
    """

    def __init__(
        self,
        host: str | None = None,
        credentials: dict[str, str] | None = None,
        *,
        rate_limiter: RateLimiter | None = None,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._host = (host or settings.CRM_API_URL).rstrip("/")
        self._credentials = dict(
            credentials
            or {"email": settings.CRM_EMAIL, "api_key": settings.CRM_API_KEY}
        )
        self._rate_limiter = rate_limiter or RateLimiter()
        self._session = session
        self._owns_session = session is None
        self._token: str | None = None
        self._auth_lock = asyncio.Lock()

    # -- жизненный цикл ---------------------------------------------------- #

    async def __aenter__(self) -> "AlfaCRMClient":
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
            self._session = aiohttp.ClientSession(timeout=timeout)
            self._owns_session = True
        await self.login()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    # -- авторизация ------------------------------------------------------- #

    async def login(self, *, force: bool = False) -> str:
        """Получить (и закешировать) токен авторизации.

        Токен ищется сначала в общем Django cache — том же, куда пишет
        синхронный ``core.crm_integration.login_to_alfa_crm`` — чтобы оба
        клиента не инвалидировали токен друг друга.

        Args:
            force: Запросить новый токен, даже если старый уже есть
                (используется при ответе 401 — истёк срок жизни токена).

        Returns:
            Токен для заголовка ``X-ALFACRM-TOKEN``.

        Raises:
            AlfaCRMError: Если CRM не вернула токен.
        """
        async with self._auth_lock:
            if self._token and not force:
                return self._token

            if force:
                cache.delete(CRM_TOKEN_CACHE_KEY)
            else:
                cached_token = cache.get(CRM_TOKEN_CACHE_KEY)
                if cached_token:
                    self._token = cached_token
                    return self._token

            payload = await self._post(
                f"{self._host}/v2api/auth/login",
                json_body=self._credentials,
                headers={"Accept": "application/json"},
            )
            token = payload.get("token")
            if not token:
                raise AlfaCRMError(f"Не удалось получить токен авторизации: {payload}")

            self._token = str(token)
            cache.set(
                CRM_TOKEN_CACHE_KEY,
                self._token,
                timeout=getattr(settings, "CRM_TOKEN_CACHE_TIMEOUT", 3600),
            )
            logger.debug("Получен новый токен AlfaCRM")
            return self._token

    # -- низкоуровневый HTTP ----------------------------------------------- #

    async def _post(
        self,
        url: str,
        *,
        json_body: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        """Выполнить POST с учётом лимита частоты и ретраев.

        Ретраим только то, что имеет смысл повторять: сетевые сбои, 429
        (слишком часто) и 5XX. Ошибки 4XX (кроме 429) отдаём сразу.

        Raises:
            AlfaCRMError: Если запрос не удался после всех попыток.
        """
        if self._session is None:
            raise AlfaCRMError("Клиент используется вне контекстного менеджера")

        last_error: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            await self._rate_limiter.acquire()
            try:
                async with self._session.post(
                    url, json=json_body, headers=headers
                ) as response:
                    status = response.status
                    if status == 200:
                        return await response.json(content_type=None)

                    body = await response.text()
                    if status == 429 or status >= 500:
                        # Временная ошибка — имеет смысл повторить.
                        last_error = AlfaCRMError(f"{url} -> HTTP {status}: {body}")
                        logger.warning(
                            "Временная ошибка %s (попытка %s/%s): %s",
                            status,
                            attempt,
                            MAX_RETRIES,
                            body[:200],
                        )
                    else:
                        raise AlfaCRMError(f"{url} -> HTTP {status}: {body}")

            except aiohttp.ClientError as exc:  # сетевые проблемы
                last_error = exc
                logger.warning(
                    "Сетевая ошибка при запросе %s (попытка %s/%s): %s",
                    url,
                    attempt,
                    MAX_RETRIES,
                    exc,
                )
            except asyncio.TimeoutError as exc:
                last_error = exc
                logger.warning(
                    "Таймаут запроса %s (попытка %s/%s)", url, attempt, MAX_RETRIES
                )

            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_BACKOFF**attempt)

        raise AlfaCRMError(f"Запрос {url} не удался после {MAX_RETRIES} попыток: {last_error}")

    async def request(
        self,
        entity: str,
        action: str = "index",
        payload: dict[str, Any] | None = None,
        *,
        branch: int | None = None,
    ) -> dict[str, Any]:
        """Вызвать CRUD-метод CRM.

        Args:
            entity: Имя сущности (``group``, ``lesson``, ``subject``, ...).
            action: Действие контроллера (``index``, ``create``, ``update``).
            payload: Тело запроса — фильтры/поля модели.
            branch: ID филиала. ``None`` — для методов вне контекста филиала.

        Returns:
            Разобранный JSON-ответ CRM.
        """
        prefix = f"/v2api/{branch}" if branch is not None else "/v2api"
        url = f"{self._host}{prefix}/{entity}/{action}"

        token = self._token or await self.login()
        headers = {
            "X-ALFACRM-TOKEN": token,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        try:
            return await self._post(url, json_body=payload or {}, headers=headers)
        except AlfaCRMError as exc:
            # Токен живёт 3600 с: по 401 обновляем его и повторяем запрос один раз.
            if "HTTP 401" not in str(exc):
                raise
            logger.info("Токен истёк, выполняется повторная авторизация")
            headers["X-ALFACRM-TOKEN"] = await self.login(force=True)
            return await self._post(url, json_body=payload or {}, headers=headers)

    async def fetch_all(
        self,
        entity: str,
        filters: dict[str, Any] | None = None,
        *,
        branch: int | None = None,
    ) -> list[dict[str, Any]]:
        """Прочитать все страницы ``index``-метода сущности.

        Ответ CRM имеет вид ``{"total":N,"count":M,"page":P,"items":[...]}``;
        страницы читаются последовательно, пока не набрано ``total`` записей
        или пока страница не вернула пустой список.

        Args:
            entity: Имя сущности.
            filters: Фильтры запроса (без ``page`` — он подставляется сам).
            branch: ID филиала.

        Returns:
            Плоский список моделей из всех страниц.
        """
        collected: list[dict[str, Any]] = []
        page = 0

        while page < MAX_PAGES:
            payload = {**(filters or {}), "page": page}
            response = await self.request(entity, "index", payload, branch=branch)

            items = response.get("items") or []
            collected.extend(items)

            total = response.get("total")
            if not items or (isinstance(total, int) and len(collected) >= total):
                break

            page += 1

        return collected


# --------------------------------------------------------------------------- #
# Промежуточные функции алгоритма                                              #
# --------------------------------------------------------------------------- #


async def fetch_tutor_groups(
    client: AlfaCRMClient,
    crm_id: int,
    branch: int,
    *,
    local_fallback: bool = True,
) -> list[dict[str, Any]]:
    """Шаг 1 схемы: получить группы наставника в конкретном филиале.

    В AlfaCRM наставник — это педагог (``Teacher``), а связь с группой хранится
    в поле ``teacher_ids`` группы. Фильтр ``teacher_id`` в ``group/index``
    документирован как «id ответственного педагога», поэтому он может не найти
    группы, где наставник указан не первым/не ответственным. Если серверный
    фильтр вернул пусто, а ``local_fallback`` включён, читаем все активные
    группы филиала и сверяем ``teacher_ids`` локально.

    Args:
        client: Авторизованный клиент CRM.
        crm_id: ID наставника (педагога) в CRM.
        branch: ID филиала.
        local_fallback: Использовать ли локальную сверку ``teacher_ids``,
            если серверный фильтр не дал результатов.

    Returns:
        Список моделей групп (только активные, ``removed=0``).
    """
    groups = await client.fetch_all(
        "group",
        {"teacher_id": crm_id, "removed": 0},
        branch=branch,
    )

    if not groups and local_fallback:
        all_groups = await client.fetch_all("group", {"removed": 0}, branch=branch)
        groups = [
            group for group in all_groups if crm_id in (group.get("teacher_ids") or [])
        ]
        if groups:
            logger.debug(
                "Филиал %s: группы наставника %s найдены локальной сверкой teacher_ids",
                branch,
                crm_id,
            )

    logger.debug("Филиал %s: найдено %s групп наставника %s", branch, len(groups), crm_id)
    return groups


def collect_group_ids(groups: Iterable[dict[str, Any]]) -> list[int]:
    """Достать уникальные ID групп из моделей, сохраняя порядок.

    Args:
        groups: Модели групп из ``group/index``.

    Returns:
        Список ID групп без дублей.
    """
    seen: dict[int, None] = {}
    for group in groups:
        group_id = group.get("id")
        if isinstance(group_id, int):
            seen.setdefault(group_id, None)
    return list(seen)


async def fetch_group_lessons(
    client: AlfaCRMClient,
    group_id: int,
    branch: int,
    date_from: date,
    date_to: date,
    statuses: Sequence[int] = DEFAULT_LESSON_STATUSES,
) -> list[dict[str, Any]]:
    """Шаг 2 схемы: получить уроки группы за неделю ПН–ВС.

    ``lesson/index`` принимает только один ``status`` за запрос, поэтому по
    статусам идём отдельными запросами и объединяем результат. Если ``status``
    не передать, CRM по умолчанию вернёт только проведённые уроки (status=3),
    поэтому параметр указывается всегда явно.

    Args:
        client: Авторизованный клиент CRM.
        group_id: ID группы.
        branch: ID филиала.
        date_from: Начало периода (понедельник), включительно.
        date_to: Конец периода (воскресенье), включительно.
        statuses: Статусы уроков (1 — запланирован, 2 — отменён, 3 — проведён).

    Returns:
        Список моделей уроков.
    """
    lessons: list[dict[str, Any]] = []

    for status in statuses:
        page = await client.fetch_all(
            "lesson",
            {
                "group_id": group_id,
                "status": status,
                "date_from": format_api_date(date_from),
                "date_to": format_api_date(date_to),
            },
            branch=branch,
        )
        lessons.extend(page)

    return lessons


async def fetch_personal_lessons(
    client: AlfaCRMClient,
    crm_id: int,
    branch: int,
    date_from: date,
    date_to: date,
    statuses: Sequence[int] = DEFAULT_LESSON_STATUSES,
) -> list[dict[str, Any]]:
    """Дополнительный шаг: уроки, где наставник указан педагогом напрямую.

    Покрывает индивидуальные и разовые уроки, не привязанные к группе, — их
    не видно на ветке «Группы -> Уроки», но доступ к предмету наставнику
    всё равно нужен.

    Args:
        client: Авторизованный клиент CRM.
        crm_id: ID наставника (педагога) в CRM.
        branch: ID филиала.
        date_from: Начало периода (понедельник), включительно.
        date_to: Конец периода (воскресенье), включительно.
        statuses: Статусы уроков.

    Returns:
        Список моделей уроков.
    """
    lessons: list[dict[str, Any]] = []

    for status in statuses:
        page = await client.fetch_all(
            "lesson",
            {
                "teacher_id": crm_id,
                "status": status,
                "date_from": format_api_date(date_from),
                "date_to": format_api_date(date_to),
            },
            branch=branch,
        )
        lessons.extend(page)

    return lessons


def extract_subject_ids(lessons: Iterable[dict[str, Any]]) -> set[int]:
    """Шаг 3 схемы: вытащить ID предметов из моделей уроков.

    Args:
        lessons: Модели уроков из ``lesson/index``.

    Returns:
        Множество ``subject_id``. Пустые и некорректные значения отбрасываются.
    """
    subject_ids: set[int] = set()

    for lesson in lessons:
        subject_id = lesson.get("subject_id")
        # bool — подкласс int, поэтому исключаем его явно; 0/None — «предмет не задан».
        if isinstance(subject_id, int) and not isinstance(subject_id, bool) and subject_id > 0:
            subject_ids.add(subject_id)

    return subject_ids


async def resolve_subject_names(
    client: AlfaCRMClient,
    subject_ids: Iterable[int],
    branch: int = BRANCH_IDS[0],
) -> dict[int, str]:
    """Сопоставить ID предметов с их названиями (для логов и проверки).

    Args:
        client: Авторизованный клиент CRM.
        subject_ids: Интересующие ID предметов.
        branch: Филиал, в котором читать справочник предметов.

    Returns:
        Словарь ``{subject_id: name}`` только по переданным ID.
    """
    wanted = set(subject_ids)
    if not wanted:
        return {}

    subjects = await client.fetch_all("subject", {}, branch=branch)
    return {
        subject["id"]: subject.get("name", "")
        for subject in subjects
        if subject.get("id") in wanted
    }


async def _collect_branch_subject_ids(
    client: AlfaCRMClient,
    crm_id: int,
    branch: int,
    date_from: date,
    date_to: date,
    statuses: Sequence[int],
    include_personal_lessons: bool,
) -> set[int]:
    """Пройти всю цепочку схемы внутри одного филиала.

    Группы -> уроки недели -> предметы уроков. Уроки всех групп запрашиваются
    конкурентно; общий лимит 5 запросов/сек соблюдает :class:`RateLimiter`.

    Returns:
        Множество ``subject_id``, найденных в этом филиале.
    """
    groups = await fetch_tutor_groups(client, crm_id, branch)
    group_ids = collect_group_ids(groups)

    tasks = [
        fetch_group_lessons(client, group_id, branch, date_from, date_to, statuses)
        for group_id in group_ids
    ]
    if include_personal_lessons:
        tasks.append(
            fetch_personal_lessons(client, crm_id, branch, date_from, date_to, statuses)
        )

    lessons_per_task = await asyncio.gather(*tasks)
    lessons = [lesson for chunk in lessons_per_task for lesson in chunk]

    subject_ids = extract_subject_ids(lessons)
    logger.info(
        "Филиал %s: групп=%s, уроков=%s, предметов=%s",
        branch,
        len(group_ids),
        len(lessons),
        len(subject_ids),
    )
    return subject_ids


# --------------------------------------------------------------------------- #
# Итоговая функция                                                             #
# --------------------------------------------------------------------------- #


async def get_tutor_subject_ids(
    crm_id: int,
    *,
    branch_ids: Sequence[int] = BRANCH_IDS,
    today: date | None = None,
    statuses: Sequence[int] = DEFAULT_LESSON_STATUSES,
    include_personal_lessons: bool = True,
    client: AlfaCRMClient | None = None,
) -> list[int]:
    """Получить ``subject_ids`` предметов наставника на ближайшую неделю ПН–ВС.

    Итоговая функция, реализующая схему целиком:

    1. вычисляет границы недели (:func:`get_week_range`) — запуск ночью с ВС на ПН
       даёт диапазон «понедельник–воскресенье» наступающей недели;
    2. по каждому филиалу компании находит группы наставника (``teacher_id=crm_id``);
    3. по каждой группе читает уроки недели в нужных статусах;
    4. опционально добирает уроки, где наставник — педагог урока;
    5. собирает уникальные ``subject_id`` уроков.

    Args:
        crm_id: ID наставника (педагога) в AlfaCRM.
        branch_ids: Филиалы, которые нужно обойти. По умолчанию все (1–4).
        today: Дата запуска (для тестов и ручного пересчёта). По умолчанию — сегодня.
        statuses: Статусы уроков, которые учитывать.
        include_personal_lessons: Учитывать ли уроки без группы, где наставник
            указан педагогом урока.
        client: Готовый клиент CRM. Если не передан — создаётся свой на время вызова.

    Returns:
        Отсортированный список уникальных ID предметов. Пустой список означает,
        что уроков на неделю нет и доступ выдавать не нужно.

    Raises:
        AlfaCRMError: При неустранимой ошибке обращения к API.
    """
    date_from, date_to = get_week_range(today)
    logger.info(
        "Наставник %s: собираем предметы за период %s — %s по филиалам %s",
        crm_id,
        format_api_date(date_from),
        format_api_date(date_to),
        list(branch_ids),
    )

    async def _run(active_client: AlfaCRMClient) -> list[int]:
        # Филиалы обходим конкурентно — запросы всё равно выстроит RateLimiter.
        per_branch = await asyncio.gather(
            *(
                _collect_branch_subject_ids(
                    active_client,
                    crm_id,
                    branch,
                    date_from,
                    date_to,
                    statuses,
                    include_personal_lessons,
                )
                for branch in branch_ids
            )
        )
        return sorted(set().union(*per_branch) if per_branch else set())

    if client is not None:
        subject_ids = await _run(client)
    else:
        async with AlfaCRMClient() as own_client:
            subject_ids = await _run(own_client)

    logger.info("Наставник %s: итоговые subject_ids=%s", crm_id, subject_ids)
    return subject_ids
