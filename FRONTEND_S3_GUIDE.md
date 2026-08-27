# Frontend Integration & S3 Storage Guide (React)

This guide explains how file storage (S3) is implemented in the KLik Resume Backend, how the React frontend interacts with file links, security measures in place, and best practices for rendering files in a React application.

---

## 1. Architecture & Backend Implementation

### S3 Storage Setup
- **Provider:** `hoster.by` (Ceph Object Storage)
- **Endpoint:** `https://storage-1022.s3hoster.by`
- **Bucket:** `storage1022`
- **Bucket ACL:** `private` (Direct public HTTP access to files is strictly prohibited)
- **Addressing Style:** `path`
- **Signature Version:** `s3v4` (AWS Signature Version 4)

### How Files Are Served
Instead of exposing raw S3 file URLs, the backend dynamically generates **Pre-signed URLs** using AWS Signature v4. 
- A Pre-signed URL includes cryptographic authentication query parameters (`X-Amz-Algorithm`, `X-Amz-Credential`, `X-Amz-Date`, `X-Amz-Expires`, `X-Amz-Signature`).
- **Time-to-Live (TTL):** Each generated URL is valid for **900 seconds (15 minutes)** from the moment it is generated.
- After 15 minutes, hoster.by S3 automatically rejects any request with an `HTTP 403 Forbidden` (`SignatureDoesNotMatch` / `RequestHasExpired`).

---

## 2. API Data Structure

### Endpoint: `GET /api/modules/`

Requires Authorization Header: `Authorization: Bearer <access_token>`

#### Sample JSON Response:

```json
[
  {
    "id": 1,
    "name": "Frontend Development Basics",
    "validity_period": 30,
    "is_active": true,
    "is_accessible": true,
    "lessons": [
      {
        "id": 10,
        "lesson_number": 1,
        "file_url": "https://storage-1022.s3hoster.by/storage1022/lessons/files/react_basics.pdf?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=...&X-Amz-Date=20260730T120000Z&X-Amz-Expires=900&X-Amz-SignedHeaders=host&X-Amz-Signature=a1b2c3d4...",
        "archive_url": "https://storage-1022.s3hoster.by/storage1022/lessons/archives/react_starter.zip?X-Amz-Algorithm=AWS4-HMAC-SHA256&..."
      },
      {
        "id": 11,
        "lesson_number": 2,
        "file_url": "https://storage-1022.s3hoster.by/storage1022/lessons/files/state_management.pdf?...",
        "archive_url": null
      }
    ]
  }
]
```

### Key Fields for Frontend

| Field | Type | Description |
|---|---|---|
| `is_accessible` | `boolean` | `true` if current user has access to this module |
| `lessons` | `array` | List of lessons if accessible, or `[]` if inaccessible |
| `lesson_number` | `number` | Sequential number of the lesson within the module |
| `file_url` | `string \| null` | Pre-signed 15-min URL for PDF file (or `null` if not attached) |
| `archive_url` | `string \| null` | Pre-signed 15-min URL for downloadable archive (or `null`) |

---

## 3. Security & Access Control

### Built-in Backend Protections

1. **Private S3 Bucket:** No file can be accessed via a clean URL (e.g. `https://storage-1022.s3hoster.by/storage1022/lessons/files/doc.pdf` will return `HTTP 403 Forbidden`).
2. **Short Lifetime (15 Mins):** Pre-signed links automatically expire to prevent link sharing and unauthorized distribution.
3. **Role-Based Access Control (RBAC):**
   - **Senior Tutors (`is_senior: true`):** Automatically granted access to all active modules and lessons (`is_accessible: true`).
   - **Regular Tutors:** Access is granted only if an unexpired `TutorModule` record exists for the tutor and module.
   - **Inaccessible Modules:** When `is_accessible` is `false`, the backend returns `lessons: []`, preventing any Pre-signed URLs from leaking to unauthorized users.
4. **Automated S3 Cleanup:** When a lesson is deleted via Django Admin or API, Django `post_delete` signals automatically delete the physical files from the S3 bucket.

### Do Frontend Developers Need Extra AWS/S3 Setup?

**NO.** 
- Do **NOT** install AWS SDK on the frontend.
- Do **NOT** store AWS Access Keys or Secrets on the frontend.
- Do **NOT** generate S3 signatures on the client.
- Simply fetch the API data and use `file_url` / `archive_url` as standard HTTP links.

---

## 4. Frontend Developer Responsibilities & Rules

1. **DO NOT Persist Pre-signed URLs:**
   - **Never** save `file_url` or `archive_url` in `localStorage`, `sessionStorage`, or persistent Redux / Zustand stores.
   - Always fetch fresh module data when the user opens the module/lesson page.
2. **Handle Expiration Gracefully:**
   - If a page stays open for more than 15 minutes without user action, clicking a file link may return HTTP 403 from S3.
   - Provide a mechanism to re-fetch module data from `/api/modules/` to refresh URLs.
3. **Handle `null` Values:**
   - Lessons may have `file_url: null` or `archive_url: null`. Render UI elements conditionally.

---

## 5. React Code Examples

### Component 1: `LessonItem.jsx` (Rendering PDF & Download Links)

```jsx
import React from 'react';

export const LessonItem = ({ lesson, onRefreshUrls }) => {
  const handleOpenPdf = (e) => {
    e.preventDefault();
    if (!lesson.file_url) return;
    
    // Open pre-signed PDF link in a new browser tab
    window.open(lesson.file_url, '_blank', 'noopener,noreferrer');
  };

  const handleDownloadArchive = (e) => {
    e.preventDefault();
    if (!lesson.archive_url) return;

    // Trigger direct browser download
    const link = document.createElement('a');
    link.href = lesson.archive_url;
    link.download = ''; // S3 headers handle file name
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="lesson-card p-4 border rounded-lg shadow-sm mb-3">
      <div className="flex justify-between items-center">
        <h4 className="font-semibold text-lg">
          Lesson #{lesson.lesson_number}
        </h4>
        
        <div className="flex gap-2">
          {/* PDF Viewer / View Button */}
          {lesson.file_url ? (
            <button
              onClick={handleOpenPdf}
              className="px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700"
            >
              📄 View PDF
            </button>
          ) : (
            <span className="text-gray-400 text-sm">No PDF</span>
          )}

          {/* Archive Download Button */}
          {lesson.archive_url ? (
            <button
              onClick={handleDownloadArchive}
              className="px-3 py-1.5 bg-green-600 text-white rounded hover:bg-green-700"
            >
              📦 Download Archive
            </button>
          ) : (
            <span className="text-gray-400 text-sm">No Archive</span>
          )}
        </div>
      </div>
    </div>
  );
};
```

---

### Component 2: Embedding PDF in React (`PdfViewerModal.jsx`)

If you want to render the PDF directly inside an `<iframe>` or embedded viewer:

```jsx
import React, { useState } from 'react';

export const PdfViewerModal = ({ fileUrl, onClose, onRefresh }) => {
  const [hasError, setHasError] = useState(false);

  if (!fileUrl) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex justify-center items-center z-50">
      <div className="bg-white w-11/12 h-5/6 rounded-xl flex flex-col overflow-hidden">
        {/* Header */}
        <div className="p-4 bg-gray-100 flex justify-between items-center border-b">
          <h3 className="font-bold">Document Viewer</h3>
          <button 
            onClick={onClose}
            className="text-gray-600 hover:text-black font-bold text-xl"
          >
            ✕
          </button>
        </div>

        {/* PDF Frame */}
        <div className="flex-1 relative">
          {hasError ? (
            <div className="flex flex-col justify-center items-center h-full p-6 text-center">
              <p className="text-red-600 font-semibold mb-3">
                Link expired or unavailable.
              </p>
              <button
                onClick={onRefresh}
                className="px-4 py-2 bg-blue-600 text-white rounded"
              >
                🔄 Refresh Link
              </button>
            </div>
          ) : (
            <iframe
              src={fileUrl}
              title="PDF Document"
              className="w-full h-full border-0"
              onError={() => setHasError(true)}
            />
          )}
        </div>
      </div>
    </div>
  );
};
```

---

### Custom React Hook: `useModules.js` (Handling API & Refreshing URLs)

```js
import { useState, useEffect, useCallback } from 'react';

export const useModules = (authToken) => {
  const [modules, setModules] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchModules = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch('/api/modules/', {
        headers: {
          'Authorization': `Bearer ${authToken}`,
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        throw new Error(`Failed to fetch modules: ${response.statusText}`);
      }

      const data = await response.json();
      setModules(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [authToken]);

  useEffect(() => {
    if (authToken) {
      fetchModules();
    }
  }, [authToken, fetchModules]);

  return { modules, loading, error, refreshModules: fetchModules };
};
```

---

## 6. Summary Checklist for Frontend Developer

- [x] Use `GET /api/modules/` with JWT Bearer Token.
- [x] Display `lesson_number` for each lesson.
- [x] Check for `null` in `file_url` and `archive_url`.
- [x] Open PDF links using `window.open(url, '_blank')` or embedded `<iframe>`.
- [x] Download archives via direct link navigation or anchor download.
- [x] Re-fetch `/api/modules/` if pre-signed links expire after 15 minutes.
- [x] Do **NOT** install AWS SDK or store S3 keys in frontend code.
