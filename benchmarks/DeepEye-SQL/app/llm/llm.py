from __future__ import annotations

import time

import threading
from typing import TYPE_CHECKING, Dict, List, Optional
from tenacity import(
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential
)
from openai import (
    OpenAI,
    AzureOpenAI,
    OpenAIError,
    AuthenticationError,
    RateLimitError,
    BadRequestError,
    APITimeoutError,
    APIConnectionError,
    InternalServerError
)
from openai.types.chat import ChatCompletionMessage
from app.logger import logger

if TYPE_CHECKING:
    from app.config.config import LLMConfig


class EmptyResponseError(Exception):
    """Custom exception for empty LLM responses, used to trigger retry."""
    pass


class _TokenBucket:
    """Shared tokens-per-minute throttle across every thread in the process.

    Without it, oversized prompts do not fail gracefully -- they 429 and retry,
    so the quota is spent on rejections instead of completions. Observed on
    bird/rap_opt1: ~221k input tokens per question, 668 rate-limit errors, and
    103 of 767 questions in 3h30m. Pacing to just under the sustained ceiling
    converts the same quota into finished work.

    Deliberately conservative: it charges the ESTIMATED prompt size plus the
    completion budget before the call, and never refunds, so it under-runs the
    limit rather than probing it.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._limit = 0
        self._spent = 0.0
        self._window_start = time.monotonic()

    def configure(self, tokens_per_minute: int) -> None:
        with self._lock:
            self._limit = max(0, int(tokens_per_minute or 0))

    def consume(self, tokens: int) -> None:
        if self._limit <= 0:
            return
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._window_start
                if elapsed >= 60.0:
                    self._window_start = now
                    self._spent = 0.0
                    elapsed = 0.0
                if self._spent + tokens <= self._limit or self._spent == 0.0:
                    self._spent += tokens
                    return
                sleep_for = 60.0 - elapsed
            logger.info(f"TPM throttle: waiting {sleep_for:.0f}s "
                        f"(would exceed {self._limit} tokens/min)")
            time.sleep(max(0.5, sleep_for))


_TOKEN_BUCKET = _TokenBucket()


def _estimate_tokens(messages, completion_budget: int) -> int:
    chars = sum(len(str(m.get("content", ""))) for m in messages)
    return int(chars / 4) + int(completion_budget or 0)


class LLM:
    """LLM wrapper class. Each instance lazily creates its own OpenAI client."""
    
    def __init__(self, llm_config: LLMConfig):
        self._config = llm_config
        self._client = None
        self._client_lock = threading.Lock()
        logger.debug(
            f"Initialized LLM wrapper: model={llm_config.model}, "
            f"temperature={llm_config.temperature}, reasoning_effort={llm_config.reasoning_effort}"
        )
    
    @property
    def llm_config(self) -> LLMConfig:
        """Get the LLM configuration."""
        return self._config
    
    def _create_client(self):
        if self._config.api_type == "openai":
            return OpenAI(api_key=self._config.api_key, base_url=self._config.base_url)
        elif self._config.api_type == "azure":
            return AzureOpenAI(api_key=self._config.api_key, base_url=self._config.base_url, api_version=self._config.api_version)
        else:
            raise ValueError(f"Unsupported api type: {self._config.api_type}")

    def _get_client(self):
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    self._client = self._create_client()
                    logger.debug(f"Created LLM client for model={self._config.model}")
        return self._client
        
    @retry(
        wait=wait_random_exponential(multiplier=1, max=60),
        stop=stop_after_attempt(15),
        # Retry on recoverable errors (including BadRequestError for provider-specific issues like "user location not supported")
        # NOT on AuthenticationError (wrong API key won't fix itself)
        retry=retry_if_exception_type((RateLimitError, APITimeoutError, APIConnectionError, InternalServerError, BadRequestError, EmptyResponseError))
    )
    def ask(self, messages: List[Dict[str, str]],
                  system_message: Optional[Dict[str, str]] = None,
                  timeout: int = 300,
                  **kwargs) -> tuple[List[ChatCompletionMessage], Dict[str, int]]:
        if system_message:
            messages = [system_message] + messages
            
        target_n = kwargs.pop("n", 1)
        max_request_n = 1 if self._config.n_call_strategy == "split" else (self._config.max_request_n or target_n)
        
        all_choices = []
        total_token_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0
        }
        
        current_max_tokens = kwargs.pop("max_tokens", self._config.max_tokens)
        
        _TOKEN_BUCKET.configure(getattr(self._config, "tokens_per_minute", 0))

        while len(all_choices) < target_n:
            current_n = min(target_n - len(all_choices), max_request_n)
            _TOKEN_BUCKET.consume(_estimate_tokens(messages, current_max_tokens) * current_n)
            try:
                request_params = {
                    "model": self._config.model,
                    "messages": messages,
                    getattr(self._config, "max_tokens_param", "max_tokens"): current_max_tokens,
                    "timeout": timeout,
                    "n": current_n,
                }
                if getattr(self._config, "send_temperature", True):
                    request_params["temperature"] = self._config.temperature
                if self._config.reasoning_effort is not None:
                    request_params["reasoning_effort"] = self._config.reasoning_effort
                if self._config.extra_body:
                    request_params["extra_body"] = self._config.extra_body
                request_params.update(kwargs)
                    
                response = self._get_client().chat.completions.create(**request_params)
                if not response.choices:
                    raise EmptyResponseError(f"No response from the model: {response}")
                
                # Check if any choice has None or empty content
                for choice in response.choices:
                    if choice.message.content is None or choice.message.content.strip() == "":
                        raise EmptyResponseError(f"Model returned empty content (possibly filtered): {response}")
                
                all_choices.extend([choice.message for choice in response.choices])
                
                # Calculate token usage
                if response.usage:
                    total_token_usage["prompt_tokens"] += response.usage.prompt_tokens
                    total_token_usage["completion_tokens"] += response.usage.completion_tokens
                    total_token_usage["total_tokens"] += response.usage.total_tokens
                
            except OpenAIError as e:
                if isinstance(e, RateLimitError):
                    logger.error(f"OpenAI error: {e}")
                    logger.error("Rate limit exceeded, please try again later.")
                elif isinstance(e, AuthenticationError):
                    logger.error(f"OpenAI error: {e}")
                    logger.error("Authentication error, please check your api key.")
                elif isinstance(e, BadRequestError):
                    error_msg = str(e).lower()
                    if "context" in error_msg or "tokens" in error_msg or "length" in error_msg:
                        new_max_tokens = int(current_max_tokens * 0.9) if current_max_tokens else 0
                        if new_max_tokens > 0:
                            logger.warning(f"Context length exceeded. Reducing max_tokens from {current_max_tokens} to {new_max_tokens} and retrying.")
                            current_max_tokens = new_max_tokens
                            continue
                        else:
                            logger.error(f"Context length exceeded, but max_tokens cannot be reduced further (current: {current_max_tokens}).")
                    
                    logger.error(f"OpenAI error: {e}")
                    logger.error("Bad request, please check your request parameters.")
                raise e
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                raise e
                
        return all_choices, total_token_usage
