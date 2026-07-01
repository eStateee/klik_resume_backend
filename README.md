# Бэкенд Klik Resume

### Авторизация через PowerShell
```powershell
Invoke-RestMethod -Uri http://localhost:8000/api/auth/login/ -Method POST -Headers @{"Content-Type"="application/json"} -Body '{"phone_number": "375291234567"}'

docker compose down -v # -v удаление и очистка БД!!!!!
docker compose down # Просто остановить 
docker compose up -d --build
docker compose exec backend python manage.py migrate_from_sqlite
docker compose exec backend python manage.py sync_tutors
docker compose exec backend python manage.py sync_groups
docker compose exec backend python manage.py sync_students
docker compose exec backend python manage.py sync_groups_remove
docker compose exec backend python manage.py sync_students_remove
