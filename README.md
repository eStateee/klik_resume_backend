# Бэкенд Klik Resume


### Сборка
```powershell
docker compose down
docker compose up -d --build
```

### Инициализация тестовых данных
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
Шаг 1 — Перенос всех данных из старой SQLite БД
Эта команда переносит всё сразу: филиалы, тьюторов, группы, студентов, резюме и отзывы в правильном порядке зависимостей.

powershell
docker compose exec backend python manage.py migrate_from_sqlite
⚠️ Требует наличия файла backend/core/db.sqlite3 внутри контейнера (смонтирован через volume ./backend:/app). Убедись, что файл лежит по пути d:\new_prog\klik_resume_backend\backend\core\db.sqlite3.

Шаг 2 — Перенос резюме и отзывов (если нужно отдельно)
Только если migrate_from_sqlite не захватил резюме (например, запускалась только часть), или для повторного переноса:

powershell
docker compose exec backend python manage.py migrate_resumes
Пропусти этот шаг, если migrate_from_sqlite уже отработал успешно — он включает резюме и отзывы (Шаг 5 внутри команды).

Шаг 3 — Синхронизация групп из CRM (актуализация)
Обновляет/создаёт группы согласно текущему состоянию CRM:

powershell
docker compose exec backend python manage.py sync_groups
Шаг 4 — Синхронизация студентов из CRM (актуализация)
Обновляет/создаёт студентов по всем группам (требует наличия групп в БД):

powershell
docker compose exec backend python manage.py sync_students
Шаг 5 — Очистка устаревших данных (опционально)
Удаляет из локальной БД то, чего больше нет в CRM. Сначала dry-run для проверки:

powershell
# Сначала проверить без удаления
docker compose exec backend python manage.py sync_groups_remove --dry-run
docker compose exec backend python manage.py sync_students_remove --dry-run
# Затем реальное удаление (если dry-run показал адекватные числа)
docker compose exec backend python manage.py sync_groups_remove
docker compose exec backend python manage.py sync_students_remove
⚠️ sync_students_remove имеет предохранитель 30% — если подлежит удалению более 30% студентов, команда остановится. Используй --force только если уверен.

Итоговый порядок
#	Команда	Что делает
0	docker compose up -d --build	Запуск + автоматические миграции
1	migrate_from_sqlite	Перенос из SQLite: филиалы → тьюторы → группы → студенты → резюме/отзывы
2	sync_groups	Актуализация групп из CRM
3	sync_students	Актуализация студентов из CRM
4	sync_groups_remove --dry-run → sync_groups_remove	Удаление неактуальных групп
5	sync_students_remove --dry-run → sync_students_remove	Удаление неактуальных студентов