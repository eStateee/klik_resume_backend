# S3 Storage Migration: Yandex Cloud → hoster.by

## Overview

The project's file storage has been migrated from **Yandex Cloud S3** (`storage.yandexcloud.net`) to **hoster.by** (`storage-1022.s3hoster.by`). The bucket `storage1022` uses a Ceph-compatible S3 API with **Signature v4** and **path-style addressing**.

No historical data migration was performed — the file storage is populated from scratch via Django Admin.

> **Important:** The endpoint hostname contains a hyphen (`storage-1022.s3hoster.by`), while the bucket name does NOT (`storage1022`). These are different identifiers and must not be confused.

---

## What Was Changed

### 1. Environment Variables (`.env` / `.env.example`)

| Variable | Old Value (Yandex Cloud) | New Value (hoster.by) |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | `test_key` | `Y9CO5XZKEHGVBRK48WAJ` |
| `AWS_SECRET_ACCESS_KEY` | `test_secret` | `29Yajh6g...` |
| `AWS_STORAGE_BUCKET_NAME` | `kiber-bucket` | `storage1022` |
| `AWS_S3_ENDPOINT_URL` | `https://storage.yandexcloud.net` | `https://storage-1022.s3hoster.by` |
| `AWS_S3_REGION_NAME` | `ru-central1` | `us-east-1` |
| `AWS_S3_ADDRESSING_STYLE` | *(not set)* | `path` |

### 2. Django Settings (`backend/_settings/settings.py`)

- Updated default fallback values for all S3 variables.
- Added `AWS_S3_ADDRESSING_STYLE` read from environment (default: `path`).
- All S3 parameters explicitly passed via `STORAGES["default"]["OPTIONS"]` dict (required for Django 5.1+):
  ```python
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
  ```

### 3. S3 Client for Pre-signed URLs (`backend/core/serializers.py`)

- `_get_s3_client()` reads `AWS_S3_ADDRESSING_STYLE` from settings dynamically.
- Uses `BotoConfig(signature_version="s3v4", s3={"addressing_style": addressing_style})`.

### 4. S3 Validation Script (`backend/test_s3.py`)

- Upload, exists-check, and delete of a test file via Django's `default_storage` API.
- Run: `docker compose exec backend python test_s3.py`

---

## How to Test (Backend)

### Prerequisites
- Docker and Docker Compose installed.
- `.env` file populated with valid hoster.by credentials.

### Step 1: Build and start

```bash
docker compose down
docker compose up -d --build
```

### Step 2: Run S3 validation script

```bash
docker compose exec backend python test_s3.py
```

**Expected output:**
```
[1/3] Загрузка тестового файла 'test_hoster_s3.txt' в S3...
      Успешно! Путь в бакете: test_hoster_s3.txt
[2/3] Проверка существования файла...
      Файл успешно найден в S3!
[3/3] Очистка: удаление тестового файла...
      Тестовый файл успешно удален из S3.

>>> ТЕСТ S3 УСПЕШНО ПРОЙДЕН! <<<
```

### Step 3: Upload via Django Admin

1. Open `http://localhost:8000/admin/` in a browser.
2. Navigate to **Core → Lessons**.
3. Create a new Lesson and attach a file to the `file` or `archive` field.
4. Save the Lesson.

**Expected:** File is uploaded to `storage-1022.s3hoster.by` without errors. No files appear in the local `/app/media/lessons/` directory.

### Step 4: Verify Pre-signed URL generation

```bash
# Authenticate
curl -X POST http://localhost:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"email": "tutor@example.com"}'

# Fetch modules with lessons
curl http://localhost:8000/api/modules/ \
  -H "Authorization: Bearer <access_token>"
```

**Expected URL format:**
```
https://storage-1022.s3hoster.by/storage1022/lessons/files/myfile.pdf?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=...&X-Amz-Expires=900&X-Amz-Signature=...
```

### Step 5: Verify URL expiration

1. Copy a `file_url` from the API response and open in browser — file downloads.
2. Wait 15+ minutes and try the same URL — returns HTTP 403.

---

## Frontend Integration Guide

### API Response Structure

The endpoint `GET /api/modules/` returns modules with nested lessons:

```json
{
  "id": 1,
  "name": "Module Name",
  "validity_period": 30,
  "is_active": true,
  "is_accessible": true,
  "lessons": [
    {
      "id": 1,
      "file_url": "https://storage-1022.s3hoster.by/storage1022/lessons/files/file.pdf?X-Amz-Algorithm=...",
      "archive_url": null
    }
  ]
}
```

### Key Points for Frontend Developers

#### 1. URLs are temporary (60 minutes)

Pre-signed URLs expire after **3600 seconds (60 minutes)**. The frontend must:
- **Fetch fresh URLs** from the API each time the user navigates to a page with downloadable content.
- **Never cache** `file_url` or `archive_url` in localStorage or persistent state.
- Component-level state (e.g., React `useState`) is fine since they refresh on re-mount.

#### 2. Handling `null` values

If a lesson has no file or archive, the field will be `null`. Conditionally render download buttons.

#### 3. File download implementation

```jsx
function LessonFiles({ lesson }) {
  if (!lesson.file_url && !lesson.archive_url) {
    return <p>No files available</p>;
  }

  return (
    <div>
      {lesson.file_url && (
        <a href={lesson.file_url} target="_blank" rel="noopener noreferrer">
          Download File
        </a>
      )}
      {lesson.archive_url && (
        <a href={lesson.archive_url} target="_blank" rel="noopener noreferrer">
          Download Archive
        </a>
      )}
    </div>
  );
}
```

#### 4. Handling expired URLs (HTTP 403)

If a download link is clicked after 15 minutes without page refresh, re-fetch module data from the API to get fresh URLs.

#### 5. Access control

Lessons are only returned when `is_accessible` is `true`. If `false`, the `lessons` array will be empty `[]`.

---

## Architecture Diagram

```
Frontend (React/Next.js)                    Backend (Django 5.1)
┌─────────────────────┐              ┌──────────────────────────┐
│                     │   GET        │                          │
│  /modules page      │─────────────>│  GET /api/modules/       │
│                     │   JSON       │                          │
│  Receives:          │<─────────────│  ModuleSerializer        │
│  - file_url         │              │   └─ LessonSerializer    │
│  - archive_url      │              │       └─ presigned URL   │
│                     │              │          (boto3 + s3v4)   │
└────────┬────────────┘              └──────────────────────────┘
         │
         │  Direct download (pre-signed URL)
         v
┌──────────────────────────────────────┐
│  hoster.by S3 (Ceph)                │
│  Endpoint: storage-1022.s3hoster.by │
│  Bucket: storage1022 (private)      │
│  Signature: AWS4-HMAC-SHA256        │
│  Addressing: path-style             │
│  Expires: 3600s                     │
└──────────────────────────────────────┘
```

---

## Summary

| Aspect | Details |
|---|---|
| **Storage Provider** | hoster.by (`storage-1022.s3hoster.by`) |
| **Bucket** | `storage1022` (private, no hyphen) |
| **Endpoint** | `https://storage-1022.s3hoster.by` (with hyphen) |
| **Signature** | AWS Signature v4 (`s3v4`) |
| **Addressing** | Path-style |
| **URL Lifetime** | 60 minutes (3600 seconds) |
| **API Endpoint** | `GET /api/modules/` → `lessons[].file_url`, `lessons[].archive_url` |
| **Upload Method** | Django Admin only |
| **Django Version** | 5.1 (uses `STORAGES` dict, not `DEFAULT_FILE_STORAGE`) |
