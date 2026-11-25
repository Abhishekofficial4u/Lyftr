import pytest
import pytest_asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, patch, MagicMock

# Set env vars before importing app
os.environ["LLM_API_KEYS"] = "test-key-1,test-key-2"
os.environ["LLM_MODEL"] = "gemini/gemini-2.0-flash"
os.environ["DATABASE_URL"] = "sqlite:///test.db"
os.environ["ALLOWED_ORIGINS"] = "http://localhost:3000"
os.environ["ENABLE_FAILURE_SIMULATION"] = "true"

from fastapi.testclient import TestClient


def _make_mock_response(content="Test response", prompt_tokens=10, completion_tokens=5):
    """Create a mock LiteLLM response."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = content
    mock_response.usage = MagicMock()
    mock_response.usage.prompt_tokens = prompt_tokens
    mock_response.usage.completion_tokens = completion_tokens
    mock_response.model = "gemini/gemini-2.0-flash"
    return mock_response


class TestHealthEndpoint:
    def test_health_returns_ok(self):
        from app.main import app
        with TestClient(app) as client:
            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert data["keys_configured"] == 2
            assert data["cache_enabled"] is True


class TestChatEndpoint:
    @patch("app.llm_service.litellm.acompletion")
    def test_chat_returns_valid_response(self, mock_completion):
        mock_completion.return_value = _make_mock_response()
        from app.main import app
        with TestClient(app) as client:
            response = client.post("/chat", json={
                "session_id": "test-session-1",
                "message": "Hello"
            })
            assert response.status_code == 200
            data = response.json()
            assert data["session_id"] == "test-session-1"
            assert data["reply"] == "Test response"
            assert data["metadata"]["resolution_source"] == "LIVE_INFERENCE"
            assert data["metadata"]["model"] == "gemini/gemini-2.0-flash"
            assert isinstance(data["metadata"]["latency_ms"], int)
            assert data["metadata"]["input_tokens"] == 10
            assert data["metadata"]["output_tokens"] == 5
            assert data["metadata"]["key_id"] is not None
            assert data["metadata"]["fallback_attempts"] == 0

    def test_chat_missing_session_id(self):
        from app.main import app
        with TestClient(app) as client:
            response = client.post("/chat", json={
                "message": "Hello"
            })
            assert response.status_code == 422

    def test_chat_empty_message(self):
        from app.main import app
        with TestClient(app) as client:
            response = client.post("/chat", json={
                "session_id": "test-session-2",
                "message": "   "
            })
            assert response.status_code == 422

    def test_chat_message_too_long(self):
        from app.main import app
        with TestClient(app) as client:
            response = client.post("/chat", json={
                "session_id": "test-session-3",
                "message": "a" * 4001
            })
            assert response.status_code == 422

    @patch("app.llm_service.litellm.acompletion")
    def test_chat_cache_hit(self, mock_completion):
        mock_completion.return_value = _make_mock_response(content="Cached answer")
        from app.main import app
        with TestClient(app) as client:
            # First request - LIVE_INFERENCE
            resp1 = client.post("/chat", json={
                "session_id": "cache-test-1",
                "message": "What is 2+2?"
            })
            assert resp1.status_code == 200
            assert resp1.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"

            # Second request with same message in new session - should cache hit
            resp2 = client.post("/chat", json={
                "session_id": "cache-test-2",
                "message": "What is 2+2?"
            })
            assert resp2.status_code == 200
            data2 = resp2.json()
            assert data2["metadata"]["resolution_source"] == "LLM_CACHE"
            assert data2["reply"] == "Cached answer"
            assert data2["metadata"]["key_id"] is None

    @patch("app.llm_service.litellm.acompletion")
    def test_simulate_failure_single_key(self, mock_completion):
        mock_completion.return_value = _make_mock_response(content="Fallback response")
        from app.main import app
        with TestClient(app) as client:
            response = client.post(
                "/chat",
                json={"session_id": "sim-test-1", "message": "Hello sim"},
                headers={"X-Simulate-Failure": "key_1=429"}
            )
            assert response.status_code == 200
            data = response.json()
            assert data["metadata"]["key_id"] == "key_2"
            assert data["metadata"]["fallback_attempts"] == 1

    @patch("app.llm_service.litellm.acompletion")
    def test_simulate_failure_all_keys(self, mock_completion):
        from app.main import app
        with TestClient(app) as client:
            response = client.post(
                "/chat",
                json={"session_id": "sim-test-2", "message": "Hello all fail"},
                headers={"X-Simulate-Failure": "*=429"}
            )
            assert response.status_code == 503
            assert response.json()["detail"] == "all providers unavailable"


class TestSessionMessages:
    @patch("app.llm_service.litellm.acompletion")
    def test_get_session_messages(self, mock_completion):
        mock_completion.return_value = _make_mock_response()
        from app.main import app
        with TestClient(app) as client:
            # Send a message first
            client.post("/chat", json={
                "session_id": "history-test-1",
                "message": "Tell me a joke"
            })

            # Get history
            response = client.get("/sessions/history-test-1/messages")
            assert response.status_code == 200
            data = response.json()
            assert data["session_id"] == "history-test-1"
            assert len(data["messages"]) >= 2
            assert data["messages"][0]["role"] == "user"
            assert data["messages"][1]["role"] == "assistant"

    def test_get_unknown_session(self):
        from app.main import app
        with TestClient(app) as client:
            response = client.get("/sessions/nonexistent/messages")
            assert response.status_code == 404
            assert response.json()["detail"] == "session not found"
