import re
import json
import logging
import requests
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict, ValidationError
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception,
    retry_if_exception_type,
    before_sleep_log,
)

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-120b"

GEMINI_MODEL    = "gemini-3-flash-preview"   # updated: Gemini 3 Flash released March 2026
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# ── Pydantic schema ───────────────────────────────────────────────────────────

class POItem(BaseModel):
    """Single line-item row extracted from a PO."""

    # populate_by_name lets us construct with either alias ("Article Code")
    # or the Python field name (article_code)
    model_config = ConfigDict(populate_by_name=True)

    article_code: Optional[str]   = Field(None, alias="Article Code")
    qty:          Optional[float] = Field(None, alias="Qty")
    price:        Optional[float] = Field(None, alias="Price")


class POResponse(BaseModel):
    """Top-level wrapper returned by the LLM."""
    items: list[POItem] = []


# ── Groq JSON schema (API-level enforcement) ──────────────────────────────────
#
# Passed as response_format so the model is *constrained* to emit this shape.
# Note: only works when the model supports structured outputs (json_schema).
# If your Groq-routed model does not, fall back to {"type": "json_object"}
# and rely on Pydantic alone.

PO_JSON_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "po_extraction",
        "strict": False,   # Groq recommends False for gpt-oss; Pydantic handles enforcement
        "schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "Article Code": {"type": ["string", "null"]},
                            "Qty":          {"type": ["number", "null"]},
                            "Price":        {"type": ["number", "null"]},
                        },
                        "required": ["Article Code", "Qty", "Price"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["items"],
            "additionalProperties": False,
        },
    },
}

# ── Shared helpers ───────────────────────────────────────────────────────────

EMPTY_RESPONSE: dict = {"items": []}


def _extract_json(text: str) -> str:
    """Strip optional ```json ... ``` fences from LLM output."""
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    return match.group(1) if match else text.strip()


def _parse_to_items(raw_text: str) -> dict:
    """
    Parse and validate raw LLM text into {"items": [...]}.

    Flow:
      1. Strip fences and JSON-parse the text (raises JSONDecodeError → tenacity retries)
      2. Normalise shape:  list → wrap,  single dict → wrap,  correct dict → pass through
      3. Validate with Pydantic POResponse (catches wrong types / missing keys)
      4. Serialise back with aliases so downstream code sees "Article Code" etc.
    """
    # Step 1 — guard against empty / whitespace-only response
    if not raw_text or not raw_text.strip():
        logger.warning("LLM returned an empty response; skipping parse.")
        return EMPTY_RESPONSE

    # Step 2 — parse
    try:
        clean  = _extract_json(raw_text)
        parsed = json.loads(clean)
    except json.JSONDecodeError as e:
        logger.warning(f"JSON parse failed: {e}")
        raise   # let tenacity retry

    # Step 3 — normalise shape
    if isinstance(parsed, list):
        raw_dict = {"items": parsed}
    elif isinstance(parsed, dict):
        if "items" in parsed and isinstance(parsed["items"], list):
            raw_dict = parsed
        else:
            logger.warning("LLM returned a single dict instead of a list; wrapping as one item.")
            raw_dict = {"items": [parsed]}
    else:
        logger.warning(f"Unexpected LLM response type: {type(parsed)}")
        return EMPTY_RESPONSE

    # Step 4 — validate with Pydantic
    try:
        validated = POResponse.model_validate(raw_dict)
    except ValidationError as e:
        logger.warning(f"Pydantic validation failed:\n{e}")
        return EMPTY_RESPONSE

    # Step 5 — serialise back to plain dict using field aliases
    #   by_alias=True  → keys are "Article Code", "Qty", "Price"
    #   exclude_none=False → keep nulls so downstream dropna() works correctly
    return validated.model_dump(by_alias=True)


# ── Groq ─────────────────────────────────────────────────────────────────────

def _is_groq_retryable(exc: Exception) -> bool:
    """Retry on network errors, rate limits, server errors, and bad JSON."""
    if isinstance(exc, json.JSONDecodeError):
        return True
    if isinstance(exc, requests.exceptions.RequestException):
        if isinstance(exc, requests.exceptions.HTTPError):
            code = exc.response.status_code if exc.response is not None else 0
            return code == 429 or code >= 500
        return True     # Timeout, ConnectionError, etc.
    return False


@retry(
    stop=stop_after_attempt(7),
    wait=wait_exponential(multiplier=5, min=10, max=300),
    retry=retry_if_exception(_is_groq_retryable),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=False,      # ← exhausted retries return EMPTY_RESPONSE below instead of raising
)
def _groq_request(prompt: str, full_text: str, api_key: str) -> dict:
    """
    Inner function decorated with tenacity.
    Raises on retryable errors so tenacity can back off and retry.
    Returns {"items": [...]} on success.
    """
    full_prompt = f"{prompt}\n\n{full_text}"

    payload = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": full_prompt}],
        "response_format": PO_JSON_SCHEMA,
        "reasoning_format": "hidden",  # suppress thinking tokens from gpt-oss-120b; they would corrupt JSON output
        "max_tokens": 2048,
        "temperature": 0,
        "top_p": 0.1,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    response = requests.post(GROQ_URL, headers=headers, json=payload, timeout=60)
    response.raise_for_status()

    data = response.json()

    try:
        raw_text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        # Malformed structure — log it and raise so tenacity retries
        logger.error("Invalid Groq response structure: %s", data)
        raise ValueError("Invalid Groq response structure")

    logger.info(f"Groq raw response received (first 200 chars):\n{raw_text[:200]}")
    return _parse_to_items(raw_text)


def call_groq(prompt: str, full_text: str, api_key: str) -> dict:
    """
    Public interface: always returns {"items": [...]}, never raises.
    Uses _groq_request (with tenacity retries) internally.
    Falls back to EMPTY_RESPONSE if all retries are exhausted.
    """
    try:
        result = _groq_request(prompt, full_text, api_key)
        # _groq_request returns None when reraise=False and retries are exhausted
        return result if result is not None else EMPTY_RESPONSE
    except Exception as e:
        logger.error(f"Groq call failed after all retries: {e}", exc_info=True)
        return EMPTY_RESPONSE


# ── Gemini ───────────────────────────────────────────────────────────────────

def _is_gemini_retryable(exc: Exception) -> bool:
    if isinstance(exc, requests.exceptions.HTTPError):
        code = exc.response.status_code if exc.response is not None else 0
        return code == 429 or code >= 500
    return isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError))


@retry(
    stop=stop_after_attempt(7),
    wait=wait_exponential(multiplier=5, min=10, max=300),
    retry=retry_if_exception(_is_gemini_retryable),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=False,      # ← same pattern as Groq
)
def _gemini_request(prompt: str, full_text: str, api_key: str) -> dict:
    """
    Inner function decorated with tenacity.
    Returns {"items": [...]} on success, raises on retryable errors.
    """
    full_prompt = f"{prompt}\n{full_text}"

    payload = {
        "contents": [{"parts": [{"text": full_prompt}]}],
        "generationConfig": {"temperature": 0, "topP": 0.1, "topK": 1},
    }

    url = f"{GEMINI_BASE_URL}/{GEMINI_MODEL}:generateContent"
    response = requests.post(
        url, params={"key": api_key}, json=payload, timeout=300
    )
    response.raise_for_status()

    data = response.json()

    try:
        raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        logger.error(f"Unexpected Gemini response format: {data}")
        raise ValueError("Invalid Gemini response structure")

    logger.info(f"Gemini raw response received (first 200 chars):\n{raw_text[:200]}")
    return _parse_to_items(raw_text)


def call_llm(prompt: str, full_text: str, api_key: str) -> dict:
    """
    Public interface for Gemini: always returns {"items": [...]}, never raises.
    Mirrors call_groq so the two are interchangeable in BaseHandler._call_llm().
    """
    try:
        result = _gemini_request(prompt, full_text, api_key)
        return result if result is not None else EMPTY_RESPONSE
    except Exception as e:
        logger.error(f"Gemini call failed after all retries: {e}", exc_info=True)
        return EMPTY_RESPONSE
