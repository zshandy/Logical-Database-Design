"""LLM client adapters (OpenAI, Gemini).

All clients are lazy-initialized so that importing this module does not require
API keys to be set in the importer's environment.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from langchain.chat_models import ChatOpenAI
from openai import OpenAI


CHAT: Optional[ChatOpenAI] = None  # LangChain wrapper, used only for stage 1
client: Optional[OpenAI] = None
gemini_client: Optional[Any] = None  # google.genai.Client


def ensure_openai(chat_max_tokens: int = 10000) -> None:
    """Lazy-init OpenAI client + LangChain CHAT.

    ``chat_max_tokens`` controls the LangChain wrapper used for stage 1 prompts;
    pass a smaller value (e.g. 2000) for pipelines that don't need long stage-1
    completions.
    """
    global CHAT, client
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY environment variable is not set.")
    if client is None:
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    if CHAT is None:
        CHAT = ChatOpenAI(
            model="gpt-4.1-mini",
            temperature=0,
            max_tokens=chat_max_tokens,
            openai_api_key=os.environ["OPENAI_API_KEY"],
        )


def ensure_gemini() -> None:
    """Lazy-init Google GenAI client."""
    global gemini_client
    if gemini_client is None:
        from google import genai
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise SystemExit("GEMINI_API_KEY environment variable is not set.")
        gemini_client = genai.Client(api_key=api_key)


def get_openai_client() -> OpenAI:
    """Return the initialized OpenAI client (call ``ensure_openai()`` first)."""
    if client is None:
        raise RuntimeError("OpenAI client not initialized; call ensure_openai() first.")
    return client


def get_gemini_client():
    """Return the initialized Gemini client (call ``ensure_gemini()`` first)."""
    if gemini_client is None:
        raise RuntimeError("Gemini client not initialized; call ensure_gemini() first.")
    return gemini_client


def get_chat() -> ChatOpenAI:
    """Return the initialized LangChain CHAT (call ``ensure_openai()`` first)."""
    if CHAT is None:
        raise RuntimeError("CHAT not initialized; call ensure_openai() first.")
    return CHAT


def chat_with_chatgpt(
    prompt: str,
    model: str = "gpt-4.1-mini",
    max_tokens: int = 10000,
) -> str:
    """Direct call to the OpenAI client; returns the assistant message text.

    ``max_tokens`` caps ``max_completion_tokens`` (default 10000). Bump it for
    long structured outputs (e.g. multi-view rename prompts).
    """
    response = get_openai_client().chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        n=1, stream=False, temperature=0.0, max_completion_tokens=max_tokens,
        top_p=1.0, frequency_penalty=0.0, presence_penalty=0.0,
    )
    return response.choices[0].message.content


def chat_with_gemini(
    prompt: str,
    model: str = "gemini-2.5-flash-lite",
    response_fields: Optional[Dict[str, type]] = None,
    max_tokens: int = 10000,
) -> str:
    """Call Gemini. If ``response_fields`` is provided (e.g. ``{"SQL": str}``),
    use structured output. ``max_tokens`` caps ``max_output_tokens``.
    """
    from google.genai import types
    from pydantic import create_model

    config_kwargs: Dict[str, Any] = dict(
        temperature=0.0, max_output_tokens=max_tokens, top_p=1.0
    )
    if response_fields:
        schema_model = create_model(
            "DynResponse", **{k: (v, ...) for k, v in response_fields.items()}
        )
        config_kwargs["response_mime_type"] = "application/json"
        config_kwargs["response_schema"] = schema_model

    response = get_gemini_client().models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(**config_kwargs),
    )
    return response.text


# Back-compat aliases — both pipelines previously called these names.
chat_with_chatgpt_DIN = chat_with_chatgpt
chat_with_gemini_DIN = chat_with_gemini
