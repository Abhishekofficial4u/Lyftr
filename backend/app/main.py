import os
import json
import time
import logging
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from dotenv import load_dotenv

from .database import Database
from .llm_service import LLMService

load_dotenv()

logger = logging.getLogger(__name__)

# Configuration
LLM_API_KEYS = os.getenv("LLM_API_KEYS", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gemini/gemini-2.5-flash")
# On Vercel or serverless, default to /tmp/app.db because the root filesystem is read-only
DATABASE_URL = os.getenv("DATABASE_URL", "/tmp/app.db" if os.getenv("VERCEL") else "sqlite:///app.db")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*")
ENABLE_FAILURE_SIMULATION = os.getenv("ENABLE_FAILURE_SIMULATION", "true").lower() == "true"
DEFAULT_SYSTEM_PROMPT = os.getenv("DEFAULT_SYSTEM_PROMPT", "You are a helpful AI assistant.")

# Global instances
db: Optional[Database] = None
llm_service: Optional[LLMService] = None


async def ensure_initialized():
    """Ensure db and llm_service are initialized (handles serverless environments)."""
    global db, llm_service
    if db is None:
        db_path = DATABASE_URL.replace("sqlite:///", "")
        db = Database(db_path)
        await db.initialize()
    if llm_service is None:
        keys = [k.strip() for k in LLM_API_KEYS.split(",") if k.strip()]
        llm_service = LLMService(
            api_keys=keys,
            model=LLM_MODEL,
            enable_cache=True,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    await ensure_initialized()
    logger.info(f"App started: {len(llm_service.api_keys)} keys, model={LLM_MODEL}, cache=enabled")
    yield
    if db:
        await db.close()


app = FastAPI(title="LLM Chatbot API", lifespan=lifespan)

# Root endpoint for browser visits
@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "Lyftr LLM Chatbot Backend",
        "health": "/health",
        "docs": "/docs"
    }

# CORS
origins = [o.strip() for o in ALLOWED_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Request / Response models ---
class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    message: str
    system_prompt: Optional[str] = None

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("message must not be empty after trimming")
        if len(trimmed) > 4000:
            raise ValueError("message must be at most 4000 characters after trimming")
        return trimmed


class MetadataResponse(BaseModel):
    resolution_source: str
    model: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    key_id: Optional[str]
    fallback_attempts: int


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    metadata: MetadataResponse


class HealthResponse(BaseModel):
    status: str
    keys_configured: int
    cache_enabled: bool


class MessageItem(BaseModel):
    role: str
    content: str
    metadata: Optional[dict] = None


class SessionMessagesResponse(BaseModel):
    session_id: str
    messages: list[MessageItem]


# --- Endpoints ---
@app.get("/health", response_model=HealthResponse)
async def health():
    await ensure_initialized()
    # Check database is reachable
    try:
        await db.health_check()
    except Exception:
        raise HTTPException(status_code=503, detail="database unreachable")

    return HealthResponse(
        status="ok",
        keys_configured=len(llm_service.api_keys),
        cache_enabled=llm_service.cache_enabled,
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, raw_request: Request):
    await ensure_initialized()
    start_time = time.time()

    # Parse failure simulation header
    simulated_failures = {}
    if ENABLE_FAILURE_SIMULATION:
        sim_header = raw_request.headers.get("x-simulate-failure", "")
        if sim_header:
            simulated_failures = _parse_simulation_header(sim_header)

    # Get system prompt for this session
    system_prompt = request.system_prompt or DEFAULT_SYSTEM_PROMPT

    # Load history from DB
    history = await db.get_messages(request.session_id)
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": request.message})

    # Call LLM through LiteLLM with failover
    try:
        result = await llm_service.complete(
            messages=messages,
            simulated_failures=simulated_failures,
        )
    except Exception as e:
        logger.error(f"All providers failed: {e}")
        raise HTTPException(status_code=503, detail="all providers unavailable")

    elapsed_ms = int((time.time() - start_time) * 1000)

    # Build metadata
    metadata = {
        "resolution_source": result["resolution_source"],
        "model": result["model"],
        "latency_ms": elapsed_ms,
        "input_tokens": result["input_tokens"],
        "output_tokens": result["output_tokens"],
        "key_id": result.get("key_id"),
        "fallback_attempts": result.get("fallback_attempts", 0),
    }

    # Store user message and assistant reply in DB
    now = datetime.now(timezone.utc).isoformat()
    await db.add_message(request.session_id, "user", request.message, None, now)
    await db.add_message(
        request.session_id, "assistant", result["reply"], json.dumps(metadata), now
    )

    return ChatResponse(
        session_id=request.session_id,
        reply=result["reply"],
        metadata=MetadataResponse(**metadata),
    )


@app.get("/sessions/{session_id}/messages", response_model=SessionMessagesResponse)
async def get_session_messages(session_id: str):
    await ensure_initialized()
    messages = await db.get_messages(session_id)
    if not messages:
        raise HTTPException(status_code=404, detail="session not found")

    items = []
    for msg in messages:
        meta = None
        if msg["metadata"]:
            try:
                full_meta = json.loads(msg["metadata"])
                meta = {
                    "resolution_source": full_meta.get("resolution_source"),
                    "input_tokens": full_meta.get("input_tokens"),
                    "output_tokens": full_meta.get("output_tokens"),
                }
            except (json.JSONDecodeError, KeyError):
                pass
        items.append(MessageItem(role=msg["role"], content=msg["content"], metadata=meta))

    return SessionMessagesResponse(session_id=session_id, messages=items)


def _parse_simulation_header(header: str) -> dict[str, int]:
    """Parse X-Simulate-Failure header: 'key_1=429,key_2=500' or '*=429'"""
    failures = {}
    for pair in header.split(","):
        pair = pair.strip()
        if "=" not in pair:
            continue
        key_id, status = pair.split("=", 1)
        try:
            failures[key_id.strip()] = int(status.strip())
        except ValueError:
            continue
    return failures
