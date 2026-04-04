import re
import json
import time
import logging
import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception, before_sleep_log, retry_if_exception_type

logger = logging.getLogger(__name__)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
GEMINI_URL_PRO = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent"

# Define which exceptions should trigger a retry
def is_retryable_error(exception):
    if isinstance(exception, requests.exceptions.HTTPError):
        if exception.response is not None:
            return exception.response.status_code == 429 or exception.response.status_code >= 500
        return False

    if isinstance(exception, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
        return True

    return False

@retry(
    # Stop after 5 attempts
    stop=stop_after_attempt(5),
    # Wait exponentially: 5s, 10s, 20s, 40s, 80s (capped at 120s)
    wait=wait_exponential(multiplier=2, min=5, max=120),
    # Only retry if it's a rate limit or server error
    retry=retry_if_exception(is_retryable_error),
    # Log before sleeping
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True
)
def call_llm(prompt: str, full_text: str, api_key: str) -> list[dict]:
    """
    Sends prompt + extracted PDF text to Gemini with exponential backoff retry.
    """
    full_prompt = f"{prompt}\n{full_text}"

    # print(full_prompt)

    payload = {
        "contents": [{"parts": [{"text": full_prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "topP": 0.1,
            "topK": 1
        }
    }

    try:

        response = requests.post(
            GEMINI_URL,
            params={"key": api_key},
            json=payload,
            timeout=300
        )
        
        # This triggers the HTTPError that 'tenacity' looks for
        response.raise_for_status()

        data = response.json()

        try:
            raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            logger.error(f"Unexpected response format: {data}")
            return []
        
        logger.info(f"LLM raw response received.\n {raw_text}...")  # log the first 200 chars


        clean = raw_text.strip().removeprefix("```json").removesuffix("```").strip()
        return json.loads(clean)

    except requests.exceptions.HTTPError as e:
        # If it's a 429, tenacity will catch this and retry
        # If it's a 400 (Bad Request), tenacity will stop and we log it here
        if e.response.status_code != 429 and e.response.status_code < 500:
            logger.error(f"Permanent API Error: {e.response.text}")
        raise e 
    except json.JSONDecodeError as e:
        logger.error(f"LLM returned invalid JSON: {e}")
        return []
    except Exception as e:
        if is_retryable_error(e):
            raise  # let tenacity retry

        logger.error(f"Unexpected error: {e}", exc_info=True)
        return []


GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    retry=retry_if_exception_type((requests.exceptions.RequestException, json.JSONDecodeError)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True
)
def call_groq(prompt: str, full_text: str, api_key: str) -> dict:
    """
    Sends prompt + extracted PDF text to Groq API with retries.
    Interface matches call_llm so you can swap easily.
    """
    full_prompt = f"{prompt}\n\n{full_text}"

    payload = {
        "model": "openai/gpt-oss-120b", # Or your preferred model
        "messages": [
            {"role": "user", "content": full_prompt}
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 2048, # Groq uses 'max_tokens', not 'max_output_tokens'
        "temperature": 0,
        "top_p": 0.1
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    try:
 
        response = requests.post(GROQ_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status()

        data = response.json()

        raw_text = ""

        try:
            raw_text = data["choices"][0]["message"]["content"]
            logger.info(f"Groq raw response received.\n {raw_text}...")  # log the first 200 chars
        except (KeyError, IndexError):
            logger.error("Retrying due to invalid response structure: %s", data)
            raise ValueError("Invalid Groq response structure")

        try:
            clean = extract_json(raw_text)
            parsed = json.loads(clean)
            if isinstance(parsed, list):
                return {"items": parsed}
            
            if isinstance(parsed, dict):
                if "items" in parsed and isinstance(parsed["items"], list):
                    return parsed
                else:
                    # Try wrapping dict as single row
                    return {"items": [parsed]}
                
            # Fallback
            logger.warning("Unexpected response format from Groq")
            return {"items": []}
        
        except json.JSONDecodeError as e:
            logger.warning(f"Retrying due to JSON decode error: {e}")
            raise e

    except json.JSONDecodeError as e:
        logger.error(f"Groq returned invalid JSON: {e}")
        return []
    except requests.exceptions.RequestException as e:
        logger.warning(f"Groq request exception: {e}")
        raise e
    except Exception as e:
        logger.error(f"Unexpected error in Groq call: {e}", exc_info=True)
        return []


def extract_json(text: str) -> str:
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1)
    return text.strip()