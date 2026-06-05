from typing import Optional

from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str
    image_base64: Optional[str] = None  # browser-compressed WEBP, base64-encoded


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    excluded_urls: list[str] = []  # URLs the user has already seen and rejected


class IntentParams(BaseModel):
    category: Optional[str] = None
    budget: Optional[str] = None          # human-readable, e.g. "under 2000 RON"
    budget_max: Optional[float] = None    # numeric ceiling for cache filtering
    budget_currency: Optional[str] = None  # ISO 4217 code
    preference: Optional[str] = None


class ProductScores(BaseModel):
    cost_efficiency: float     # 40% weight
    quality_confidence: float  # 35% weight
    logistics: float           # 15% weight
    trust: float               # 10% weight


class Product(BaseModel):
    rank: int
    title: str
    url: str
    price: Optional[float] = None
    currency: Optional[str] = None
    image_url: Optional[str] = None
    scores: ProductScores
    value_score: float
    reasoning: str


class ChatResponse(BaseModel):
    intent: str  # "CHAT" | "CLARIFY" | "SEARCH"
    reply: Optional[str] = None
    products: Optional[list[Product]] = None
    collected_params: IntentParams
    from_cache: bool = False
    fallback_message: Optional[str] = None
