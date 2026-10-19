# backend/llm_client.py
"""
Minimal, crash-proof Ollama client for the backend.

Deliberately NOT SEC10K.OllamaInterface — that class tries to install/start
Ollama and calls `sys.exit(1)` on Windows if it isn't running. That's fine
for a CLI script the user is watching; it would take down the entire
FastAPI process if reused inside a background scan worker. Everything here
just returns None on failure so callers degrade gracefully instead.
"""

from typing import List, Optional

import requests

OLLAMA_BASE_URL = "http://localhost:11434"


def is_available(base_url: str = OLLAMA_BASE_URL, timeout: float = 2.0) -> bool:
    try:
        resp = requests.get(f"{base_url}/api/tags", timeout=timeout)
        return resp.status_code == 200
    except requests.RequestException:
        return False


def chat(messages, model: str = "llama3.2", base_url: str = OLLAMA_BASE_URL,
         max_tokens: int = 300, temperature: float = 0.1, timeout: float = 30.0) -> Optional[str]:
    try:
        resp = requests.post(
            f"{base_url}/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": temperature, "num_predict": max_tokens},
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "") or None
    except (requests.RequestException, ValueError):
        return None


def classify_into_categories(text: str, categories: List[str], model: str = "llama3.2") -> Optional[str]:
    """
    Ask the model to pick exactly one label from `categories` (or "none").

    This never lets the model invent a category outside the provided list
    — the response is matched back against the exact strings given — so
    it can't be used to hallucinate a supplier ticker that isn't already
    in the taxonomy. It only ever picks among vetted options.
    """
    if not categories or not is_available():
        return None

    options = "\n".join(f"- {c}" for c in categories)
    messages = [
        {
            "role": "system",
            "content": "Respond with ONLY the exact text of one option, nothing else.",
        },
        {
            "role": "user",
            "content": f"""Which of these categories best matches this text? If none fit well, respond with "none".

Text:
{text[:800]}

Options:
{options}

Respond with the exact option text, or "none".""",
        },
    ]

    response = chat(messages, model=model, max_tokens=50)
    if not response:
        return None

    response_clean = response.strip().strip('"').strip()
    if response_clean.lower() == "none":
        return None

    for category in categories:
        if category.lower() in response_clean.lower():
            return category
    return None
