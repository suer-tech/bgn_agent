import json
import os
from typing import Any, Dict, List, Type, TypeVar

from openai import OpenAI
from pydantic import BaseModel

from agents.execution_agent import NextStep

T = TypeVar("T", bound=BaseModel)

# ANSI colors
CLI_RED = "\x1b[31m"
CLI_YELLOW = "\x1b[33m"
CLI_GREEN = "\x1b[32m"
CLI_CLR = "\x1b[0m"


class LLMProvider:
    """Base class for LLM providers."""

    def complete(self, messages: List[Dict[str, Any]]) -> NextStep:
        raise NotImplementedError

    def complete_as(self, messages: List[Dict[str, Any]], response_type: Type[T]) -> T:
        raise NotImplementedError


class OpenRouterProvider(LLMProvider):
    def __init__(self, model: str):
        api_key = os.getenv("OPENROUTER_API_KEY")
        base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY environment variable is not set")
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def complete(self, messages: List[Dict[str, Any]]) -> NextStep:
        return self.complete_as(messages, NextStep)

    def complete_as(self, messages: List[Dict[str, Any]], response_type: Type[T]) -> T:
        resp = self.client.beta.chat.completions.parse(
            model=self.model,
            response_format=response_type,
            messages=messages,
            max_completion_tokens=16384,
        )
        parsed = resp.choices[0].message.parsed
        if parsed is None:
            raise ValueError(f"LLM returned None for {response_type.__name__}")
        return parsed


def create_provider() -> LLMProvider:
    """Factory function to create the configured LLM provider."""
    provider_name = os.getenv("LLM_PROVIDER", "openrouter").lower()
    model = os.getenv("LLM_MODEL", "openai/gpt-4.1-mini")

    if provider_name == "openrouter":
        print(f"{CLI_GREEN}Using OpenRouter provider with model: {model}{CLI_CLR}")
        return OpenRouterProvider(model=model)
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider_name}. Use 'openrouter'.")
