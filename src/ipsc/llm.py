import json
import os
import re
import time

import httpx

TIMEOUT = 60


class LLMError(RuntimeError):
    pass


def _groq(system: str, user: str) -> str:
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise LLMError("GROQ_API_KEY not set")
    model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    body = {"model": model, "temperature": 0,
            "messages": [{"role": "system", "content": system + " Output a single JSON object and nothing else."},
                         {"role": "user", "content": user}]}
    if "gpt-oss" in model:
        # Reasoning models can exhaust the budget thinking and return empty content.
        body["reasoning_effort"] = "low"
        body["max_completion_tokens"] = 4000
    r = httpx.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"}, json=body, timeout=TIMEOUT)
    if r.status_code != 200:
        raise LLMError(f"Groq {r.status_code}: {r.text[:200]}")
    content = r.json()["choices"][0]["message"].get("content") or ""
    if not content.strip():
        raise LLMError("Groq returned empty content")
    return content


def _gemini(system: str, user: str) -> str:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise LLMError("GEMINI_API_KEY not set")
    model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    r = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": key},
        json={"systemInstruction": {"parts": [{"text": system}]},
              "contents": [{"role": "user", "parts": [{"text": user}]}],
              "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}},
        timeout=TIMEOUT)
    if r.status_code != 200:
        raise LLMError(f"Gemini {r.status_code}: {r.text[:200]}")
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


PROVIDERS = {"groq": _groq, "gemini": _gemini}


def complete_json(system: str, user: str, log=lambda m: None) -> dict:
    """Call the primary provider, fall back to the secondary one on any failure."""
    order = [os.getenv("LLM_PROVIDER", "groq").lower()]
    fb = os.getenv("LLM_FALLBACK", "").lower()
    if fb and fb not in order:
        order.append(fb)
    errors = []
    for name in order:
        fn = PROVIDERS.get(name)
        if not fn:
            errors.append(f"unknown provider {name}")
            continue
        for attempt in (1, 2):
            try:
                raw = fn(system, user)
                m = re.search(r"\{.*\}", raw, re.S)
                return json.loads(m.group(0) if m else raw)
            except (LLMError, httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError) as e:
                if attempt == 2:
                    errors.append(f"{name}: {e}")
                log(f"  LLM {name} attempt {attempt} failed: {str(e)[:120]}")
                if attempt == 1:
                    time.sleep(15 if "429" in str(e) else 2)
    raise LLMError("; ".join(errors))
