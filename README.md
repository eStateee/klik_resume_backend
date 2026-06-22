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
API `http://localhost:8000/api/` 
