# Бэкенд Klik Resume

## Особенности
- **Беспарольная аутентификация**: Менеджеры и тьюторы входят в систему, используя только свой номер телефона.
- **Кастомная JWT-аутентификация**: Защищает API с помощью JSON Web Tokens (JWT), привязанных к моделям `Manager` и `TutorProfile`.
- **Ролевая модель доступа**: Строгие ограничения доступа в зависимости от роли (Тьютор, Старший тьютор, Менеджер) и филиала.
- **Интеграция с CRM**: Токен CRM кэшируется в Redis на 1 час (3600 секунд) для оптимизации запросов к внешнему API.


## Тайминги JWT
### 'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
### 'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
## Быстрый старт

### Сборка и запуск проекта
```powershell
docker compose down
docker compose up -d --build
```

### Инициализация тестовых данных
Выполните следующую команду для добавления тестовых данных в базу:
```powershell
docker compose exec backend python init_data.py
```

## Документация API и Использование

Корневой URL API `http://localhost:8000/api/` автоматически перенаправляет на интерактивную документацию Swagger.

### Как авторизоваться в Swagger
1. Перейдите в Swagger UI: [http://localhost:8000/api/docs/swagger/](http://localhost:8000/api/docs/swagger/)
2. Прокрутите до эндпоинта `POST /api/auth/login/` и разверните его.
3. Нажмите **"Try it out"** и введите корректный номер телефона из тестовых данных (например, `"375291234567"`).
4. Выполните запрос (Execute) и скопируйте токен `access` из тела ответа.
5. Прокрутите обратно наверх страницы и нажмите кнопку **"Authorize"**.
6. Вставьте скопированный токен в поле `jwtAuth` (добавлять префикс "Bearer " не нужно, Swagger сделает это автоматически) и нажмите **"Authorize"**.
7. Теперь вы можете тестировать защищенные эндпоинты!

### Пример: Авторизация через PowerShell
```powershell
Invoke-RestMethod -Uri http://localhost:8000/api/auth/login/ -Method POST -Headers @{"Content-Type"="application/json"} -Body '{"phone_number": "375291234567"}'
```
