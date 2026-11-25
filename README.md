# LLM Chatbot with Key Failover and Response Caching

A full-stack AI chatbot application with automatic API key failover, response caching, and per-request token tracking.

## 1. Live URLs

- **Frontend**: _[Deploy to Vercel/Netlify and add URL here]_
- **Backend**: _[Deploy to Render/Railway and add URL here]_

## 2. Run Locally

### With Docker (recommended)

```bash
# 1. Clone the repository
git clone <repo-url>
cd Lyftr

# 2. Create .env file from example
cp .env.example .env
# Edit .env with your actual API keys

# 3. Start the stack
make up

# Frontend: http://localhost:3000
# Backend:  http://localhost:8000
```

To stop:
```bash
make down
```

### Without Docker

**Backend:**
```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Set environment variables
export LLM_API_KEYS="your-key-1,your-key-2"
export DATABASE_URL="sqlite:///app.db"
export ALLOWED_ORIGINS="http://localhost:3000,http://localhost:5173"
export ENABLE_FAILURE_SIMULATION="true"

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Frontend:**
```bash
cd frontend
npm install
VITE_API_URL=http://localhost:8000 npm run dev
```

**Run backend tests:**
```bash
cd backend
pip install -r requirements.txt
pytest -v
```

## 3. Design Decisions

### Key Fallback
- API keys are stored as a comma-separated pool in `LLM_API_KEYS`
- Keys are assigned sequential IDs: `key_1`, `key_2`, etc.
- On failure (429, quota errors, 5xx), the system automatically tries the next key
- The `X-Simulate-Failure` header enables testing failover without exhausting real keys
- If all keys fail, a clean 503 response is returned

### Caching
- In-memory cache using SHA-256 hash of the full message list (system prompt + history + new message)
- Cache hits return identical reply text with `LLM_CACHE` source label
- Cache hits are significantly faster since no LLM call is made
- `key_id` is `null` and `fallback_attempts` is `0` on cache hits
- Same first message in different sessions hits cache (same message list → same hash)

### SQLite Session Storage
- History is stored per `session_id` in a single `messages` table
- Schema auto-creates on startup
- Database location is configurable via `DATABASE_URL`
- Docker volume at `/data` ensures persistence across container restarts
- Each message stores role, content, metadata (JSON for assistant messages), and ISO-8601 timestamp

## 4. Verification

### Failover
```bash
# Key 1 fails → falls back to Key 2
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-Simulate-Failure: key_1=429" \
  -d '{"session_id": "test-1", "message": "Hello"}'
# → key_id: "key_2", fallback_attempts: 1

# All keys fail → 503
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-Simulate-Failure: *=429" \
  -d '{"session_id": "test-2", "message": "Hello"}'
# → 503 {"detail": "all providers unavailable"}
```

### Cache Hits
```bash
# First request → LIVE_INFERENCE
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id": "cache-1", "message": "What is 2+2?"}'

# Same message in new session → LLM_CACHE (faster)
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id": "cache-2", "message": "What is 2+2?"}'
```

### Token Usage
Each response includes `input_tokens` and `output_tokens` in the metadata, displayed per-message in the UI alongside the model name and latency.

### Session History
```bash
curl http://localhost:8000/sessions/test-1/messages
```

## 5. Setup Used

- **Editor**: Antigravity AI Assistant
- **AI Tools**: Claude for code generation and architecture decisions
- **Tech Stack**: FastAPI + LiteLLM (backend), React + Vite (frontend), SQLite, Docker

## 6. Bonus Features

- **System Prompt Override**: Users can set a custom system prompt per session via the UI
- **Typing Indicator**: Animated dots while waiting for the AI response
- **Error Handling UI**: Errors appear as styled messages in the chat, never blank screens
- **Responsive Design**: Clean, mobile-friendly UI with smooth animations
- **Session Badge**: Shows the current session ID in the header
