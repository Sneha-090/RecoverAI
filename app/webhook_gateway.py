"""Public tunnel target exposing only the signed Razorpay webhook route.

Run: python -m uvicorn app.webhook_gateway:app --host 127.0.0.1 --port 8002
Keep operator APIs on a separate local/private listener.
"""

from fastapi import FastAPI

from app.api.webhooks import router


app = FastAPI(title="RecoverAI webhook gateway", docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(router)
