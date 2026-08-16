from fastapi import FastAPI

from app.api.approvals import router as approvals_router
from app.api.dev_auth import router as dev_auth_router
from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.api.me import router as me_router
from app.api.retrieve import router as retrieve_router
from app.api.runs import router as runs_router
from app.api.test_hooks import router as test_hooks_router
from app.api.tickets import router as tickets_router

app = FastAPI(title="FlowForge-AI")
app.include_router(health_router)
app.include_router(me_router)
app.include_router(documents_router)
app.include_router(retrieve_router)
app.include_router(tickets_router)
app.include_router(runs_router)
app.include_router(approvals_router)
# Dev-only; every route 404s when APP_ENV=prod.
app.include_router(test_hooks_router)
# Dev-only token issuance: 404s in prod and whenever Auth0 is the live
# provider. The unauthenticated stand-in for Auth0's /oauth/token.
app.include_router(dev_auth_router)
