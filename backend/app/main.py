from fastapi import FastAPI

app = FastAPI(title="FlowForge-AI")


@app.get("/api/health")
async def health() -> dict[str, str]:
    # Stub — replaced with real db/redis pings in the health router (task 7).
    return {"status": "ok"}
