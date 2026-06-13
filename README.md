## Токен CRM кэшируется на 1 час (3600 секунд).

**Команда для добавления тестовых данных:**
```powershell
docker compose exec backend python init_data.py
```

**Отправьте POST-запрос для входа тьютора:**
```powershell
Invoke-RestMethod -Uri http://localhost:8000/api/auth/login/ -Method POST -Headers @{"Content-Type"="application/json"} -Body '{"phone_number": "375291234567"}'
```





**Команда для добавления тестовых данных:**
```powershell
docker compose down
docker compose up -d --build
```
