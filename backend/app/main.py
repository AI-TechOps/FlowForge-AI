from fastapi import FastAPI

from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.api.retrieve import router as retrieve_router
from app.api.runs import router as runs_router
from app.api.tickets import router as tickets_router

app = FastAPI(title="FlowForge-AI")
app.include_router(health_router)
app.include_router(documents_router)
app.include_router(retrieve_router)
app.include_router(tickets_router)
app.include_router(runs_router)
