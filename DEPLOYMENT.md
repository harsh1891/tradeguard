# Deploy TradeGuard

The easiest deployment path is Render because the dashboard is served directly by the FastAPI backend.

## Render

1. Push this project to GitHub.
2. Open Render.
3. Choose **New > Blueprint**.
4. Connect your GitHub repository.
5. Render will detect `render.yaml`.
6. Deploy the `tradeguard` service.

After deploy, your public link will look like:

```text
https://tradeguard.onrender.com
```

The root URL redirects to the dashboard automatically.

Useful URLs:

```text
/              Dashboard redirect
/dashboard     Dashboard page
/docs          FastAPI API docs
/health        Health check
```

## Local Production Command

From the project root:

```powershell
.\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```
