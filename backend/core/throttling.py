from rest_framework.throttling import AnonRateThrottle


class LoginRateThrottle(AnonRateThrottle):
    """
    Ограничение частоты попыток входа с одного адреса.

    Вход в проекте беспарольный — знание номера телефона даёт полный доступ
    к аккаунту, поэтому перебор номеров нужно ограничивать. Лимит задаётся
    настройкой DEFAULT_THROTTLE_RATES['login'] (переменная THROTTLE_LOGIN).
    """

    scope = "login"


class ParentReviewCreateThrottle(AnonRateThrottle):
    """
    Ограничение частоты отправки отзывов родителями.

    Эндпоинт создания отзыва публичный (родитель заполняет форму без входа),
    поэтому без лимита он открыт для спама. Лимит задаётся настройкой
    DEFAULT_THROTTLE_RATES['review'] (переменная THROTTLE_REVIEW).
    """

    scope = "review"
