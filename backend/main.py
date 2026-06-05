from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from routers import auth, plan, search, webhooks


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Warm the retailers cache from Supabase so the first request doesn't block.
    from services import retailers_service
    retailers_service.preload()
    yield


app = FastAPI(title="SmartShop Assistant API", lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(plan.router)
app.include_router(search.router)
app.include_router(webhooks.router)


@app.get("/")
async def health():
    return {"status": "ok"}
