from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import auth, plan, webhooks

app = FastAPI(title="SmartShop Assistant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(plan.router)
app.include_router(webhooks.router)


@app.get("/")
async def health():
    return {"status": "ok"}
