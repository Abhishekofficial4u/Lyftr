import hashlib
import json
import logging
import time
from typing import Optional

import litellm

logger = logging.getLogger(__name__)

# Suppress litellm's noisy logs
litellm.suppress_debug_info = True


class AllProvidersUnavailableError(Exception):
    """Raised when every key in the pool fails."""
    pass


class LLMService:
    """Handles LLM calls with key-pool failover and disk-based caching via LiteLLM."""

    def __init__(
        self,
        api_keys: list[str],
        model: str = "gemini/gemini-2.5-flash",
        enable_cache: bool = True,
    ):
        self.api_keys = api_keys
        self.model = model
        self.cache_enabled = enable_cache

        # In-memory cache: maps message hash -> cached response dict
        self._cache: dict[str, dict] = {}

    def _cache_key(self, messages: list[dict]) -> str:
        """Deterministic hash of the full message list for caching."""
        raw = json.dumps(messages, sort_keys=True, ensure_ascii=True)
        return hashlib.sha256(raw.encode()).hexdigest()

    async def complete(
        self,
        messages: list[dict],
        simulated_failures: Optional[dict[str, int]] = None,
    ) -> dict:
        """
        Call the LLM with failover across the key pool.
        Returns a dict with: reply, resolution_source, model, input_tokens,
        output_tokens, key_id, fallback_attempts.
        """
        if simulated_failures is None:
            simulated_failures = {}

        # --- Check cache first ---
        if self.cache_enabled:
            cache_key = self._cache_key(messages)
            cached = self._cache.get(cache_key)
            if cached:
                logger.info("Cache HIT")
                return {
                    "reply": cached["reply"],
                    "resolution_source": "LLM_CACHE",
                    "model": cached["model"],
                    "input_tokens": cached["input_tokens"],
                    "output_tokens": cached["output_tokens"],
                    "key_id": None,
                    "fallback_attempts": 0,
                }

        # --- Try each key in the pool ---
        fallback_attempts = 0
        last_error = None

        for idx, api_key in enumerate(self.api_keys):
            key_id = f"key_{idx + 1}"

            # Check simulated failures
            if simulated_failures:
                sim_status = simulated_failures.get(key_id) or simulated_failures.get("*")
                if sim_status:
                    logger.info(f"Simulated failure for {key_id}: HTTP {sim_status}")
                    fallback_attempts += 1
                    last_error = Exception(f"Simulated {sim_status} for {key_id}")
                    continue

            try:
                response = await litellm.acompletion(
                    model=self.model,
                    messages=messages,
                    api_key=api_key,
                    timeout=30,
                )

                reply = response.choices[0].message.content or ""
                usage = response.usage
                model_used = response.model or self.model

                result = {
                    "reply": reply,
                    "resolution_source": "LIVE_INFERENCE",
                    "model": self.model,
                    "input_tokens": usage.prompt_tokens if usage else 0,
                    "output_tokens": usage.completion_tokens if usage else 0,
                    "key_id": key_id,
                    "fallback_attempts": fallback_attempts,
                }

                # Store in cache
                if self.cache_enabled:
                    self._cache[cache_key] = {
                        "reply": reply,
                        "model": self.model,
                        "input_tokens": result["input_tokens"],
                        "output_tokens": result["output_tokens"],
                    }

                return result

            except Exception as e:
                error_str = str(e).lower()
                # Check if it's a retryable error (429, quota, 5xx)
                is_retryable = any(
                    code in error_str
                    for code in ["429", "rate_limit", "quota", "500", "502", "503", "529"]
                )
                if is_retryable or "rate" in error_str:
                    logger.warning(f"Key {key_id} failed with retryable error: {e}")
                    fallback_attempts += 1
                    last_error = e
                    continue
                else:
                    # Non-retryable error, still try next key
                    logger.error(f"Key {key_id} failed with non-retryable error: {e}")
                    fallback_attempts += 1
                    last_error = e
                    continue

        # All keys exhausted
        raise AllProvidersUnavailableError(
            f"All {len(self.api_keys)} providers unavailable. Last error: {last_error}"
        )
