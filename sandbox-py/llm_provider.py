import json
import os
import subprocess
from typing import Any, Dict, List, Type, TypeVar

from openai import OpenAI
from pydantic import BaseModel

from agent import LLMProvider, NextStep

T = TypeVar("T", bound=BaseModel)

# ANSI colors
CLI_RED = "\x1b[31m"
CLI_YELLOW = "\x1b[33m"
CLI_GREEN = "\x1b[32m"
CLI_CYAN = "\x1b[36m"
CLI_CLR = "\x1b[0m"
CLI_DIM = "\x1b[90m"


def messages_to_prompt(messages: List[Dict[str, Any]]) -> str:
    """Convert OpenAI-style messages list to a single prompt string."""
    prompt_parts = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        tool_calls = msg.get("tool_calls")

        if role == "system":
            prompt_parts.append(f"=== SYSTEM ===\n{content}")
        elif role == "user":
            prompt_parts.append(f"=== USER ===\n{content}")
        elif role == "assistant":
            if tool_calls:
                tc_str = json.dumps(tool_calls, indent=2, ensure_ascii=False)
                prompt_parts.append(
                    f"=== ASSISTANT (tool call) ===\nReasoning: {content}\nTool call: {tc_str}"
                )
            else:
                prompt_parts.append(f"=== ASSISTANT ===\n{content}")
        elif role == "tool":
            tool_id = msg.get("tool_call_id", "?")
            prompt_parts.append(f"=== TOOL RESULT (id: {tool_id}) ===\n{content}")

    return "\n\n".join(prompt_parts)


def build_schema_hint_for_type(response_type: Type[BaseModel]) -> str:
    """Build a human-readable JSON schema hint from a Pydantic model."""
    schema = response_type.model_json_schema()
    schema_str = json.dumps(schema, indent=2, ensure_ascii=False)
    return f"""You MUST respond with a valid JSON object matching this schema:

{schema_str}

Respond ONLY with the JSON object. No markdown, no explanation."""


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


class ManualProvider(LLMProvider):
    """Provider that outputs prompts and waits for manual JSON input.

    Use this with opencode or any other LLM that doesn't support structured output.
    You paste the prompt into your LLM, get JSON back, paste it here.
    """

    def __init__(self):
        print(f"{CLI_CYAN}Manual LLM provider active.{CLI_CLR}")
        print(f"{CLI_DIM}Workflow:{CLI_CLR}")
        print(f"{CLI_DIM}  1. Program shows you a prompt{CLI_CLR}")
        print(f"{CLI_DIM}  2. Copy prompt to your LLM (opencode){CLI_CLR}")
        print(f"{CLI_DIM}  3. LLM responds with JSON{CLI_CLR}")
        print(f"{CLI_DIM}  4. Paste the JSON back here{CLI_CLR}\n")

    def complete(self, messages: List[Dict[str, Any]]) -> NextStep:
        return self.complete_as(messages, NextStep)

    def complete_as(self, messages: List[Dict[str, Any]], response_type: Type[T]) -> T:
        full_prompt = messages_to_prompt(messages)
        schema_hint = build_schema_hint_for_type(response_type)

        # Output for the user
        print(f"\n{CLI_YELLOW}{'=' * 60}")
        print(f"COPY THE PROMPT BELOW AND SEND TO YOUR LLM:")
        print(f"{'=' * 60}{CLI_CLR}\n")
        print(full_prompt)
        print(f"\n{CLI_CYAN}{'=' * 60}")
        print(f"RESPONSE FORMAT (paste JSON matching this schema):")
        print(f"{'=' * 60}{CLI_CLR}")
        print(schema_hint)
        print(f"\n{CLI_CYAN}{'=' * 60}")
        print(f"PASTE THE JSON FROM YOUR LLM BELOW")
        print(f"(paste JSON, then press Enter on empty line to submit):")
        print(f"{'=' * 60}{CLI_CLR}\n")

        # Retry loop for parsing
        max_retries = 3
        for attempt in range(max_retries):
            raw_text = self._read_multiline_input()
            if not raw_text:
                if attempt < max_retries - 1:
                    print(
                        f"{CLI_YELLOW}Empty input. Paste JSON and press Enter twice.{CLI_CLR}\n"
                    )
                    continue
                else:
                    raise ValueError("No input provided after 3 attempts")

            json_text = self._extract_json(raw_text)

            try:
                data = json.loads(json_text)
                return response_type.model_validate(data)
            except (json.JSONDecodeError, Exception) as e:
                if attempt < max_retries - 1:
                    print(f"\n{CLI_YELLOW}Parse error: {e}{CLI_CLR}")
                    print(f"{CLI_YELLOW}Your input was:{CLI_CLR}")
                    print(f"{CLI_DIM}{raw_text[:300]}{CLI_CLR}")
                    print(
                        f"\n{CLI_YELLOW}Please paste valid JSON (attempt {attempt + 2}/{max_retries}):{CLI_CLR}\n"
                    )
                else:
                    print(f"{CLI_YELLOW}Failed after {max_retries} attempts.{CLI_CLR}")
                    print(f"{CLI_YELLOW}Last input:{CLI_CLR}")
                    print(raw_text[:500])
                    raise ValueError(f"Failed to parse LLM response as JSON: {e}")

    def _read_multiline_input(self) -> str:
        """Read multi-line JSON input from user."""
        lines = []
        while True:
            try:
                line = input()
            except EOFError:
                break

            lines.append(line)
            current_text = "\n".join(lines)

            if "{" in current_text and "}" in current_text:
                break
            if line.strip() == "" and len(lines) > 1:
                break
            if line.strip() == "" and len(lines) == 1:
                lines = []
                continue

        return "\n".join(lines).strip()

    def _extract_json(self, text: str) -> str:
        """Extract JSON from text that might contain markdown fences or extra text.
        Auto-closes missing brackets."""
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        start = text.find("{")
        if start == -1:
            return text

        json_part = text[start:]

        open_braces = json_part.count("{")
        close_braces = json_part.count("}")
        open_brackets = json_part.count("[")
        close_brackets = json_part.count("]")

        if close_brackets < open_brackets:
            json_part += "]" * (open_brackets - close_brackets)
        if close_braces < open_braces:
            json_part += "}" * (open_braces - close_braces)

        return json_part


class OpencodeProvider(LLMProvider):
    """Provider that calls opencode CLI automatically.

    Sends prompt to opencode run, parses JSON events, extracts text response,
    and parses it into the requested Pydantic model.
    """

    def __init__(self):
        print(f"{CLI_GREEN}Using opencode provider{CLI_CLR}")

    def complete(self, messages: List[Dict[str, Any]]) -> NextStep:
        return self.complete_as(messages, NextStep)

    def complete_as(self, messages: List[Dict[str, Any]], response_type: Type[T]) -> T:
        full_prompt = messages_to_prompt(messages)
        schema_hint = build_schema_hint_for_type(response_type)
        full_prompt = full_prompt + "\n\n=== RESPONSE FORMAT ===\n" + schema_hint

        print(f"{CLI_DIM}Calling opencode...{CLI_CLR}")

        try:
            prompt_bytes = full_prompt.encode("utf-8")
            result = subprocess.run(
                ["opencode", "run", "--format", "json"],
                input=prompt_bytes,
                capture_output=True,
                timeout=120,
                shell=True,
            )
            stdout = result.stdout.decode("utf-8", errors="replace")
            stderr = result.stderr.decode("utf-8", errors="replace")

            if result.returncode != 0:
                raise ValueError(f"opencode failed: {stderr}")

            print(f"{CLI_DIM}Raw stdout: {len(stdout)} chars{CLI_CLR}")

            text_response = self._extract_text_from_events(stdout)

            if not text_response:
                print(f"{CLI_YELLOW}DEBUG: stdout sample: {stdout[:500]}{CLI_CLR}")
                raise ValueError("No text response from opencode")

            print(f"{CLI_DIM}Got response ({len(text_response)} chars){CLI_CLR}")
            print(f"{CLI_DIM}Response preview: {text_response[:200]}...{CLI_CLR}")

            json_text = self._extract_json(text_response)

            print(f"{CLI_DIM}JSON part: {json_text[:200]}...{CLI_CLR}")

            data = json.loads(json_text)
            return response_type.model_validate(data)

        except subprocess.TimeoutExpired:
            raise ValueError("opencode timed out after 120 seconds")
        except Exception as e:
            print(f"{CLI_RED}opencode error: {e}{CLI_CLR}")
            raise

    def _extract_text_from_events(self, stdout: str) -> str:
        """Extract text content from opencode JSON events."""
        combined_text = []
        event_types = set()

        for line in stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                event_type = event.get("type", "unknown")
                event_types.add(event_type)

                if event_type == "text":
                    part = event.get("part", {})
                    text = part.get("text", "")
                    if text:
                        combined_text.append(text)
                elif event_type == "content":
                    content = event.get("content", {})
                    if isinstance(content, str):
                        combined_text.append(content)
                    elif isinstance(content, dict):
                        text = content.get("text", "")
                        if text:
                            combined_text.append(text)
                elif event_type == "message":
                    text = event.get("text", "")
                    if text:
                        combined_text.append(text)
            except json.JSONDecodeError:
                if line and len(line) > 10:
                    combined_text.append(line)
                continue

        if event_types:
            print(f"{CLI_DIM}Opencode event types: {event_types}{CLI_CLR}")

        return "\n".join(combined_text)

    def _extract_json(self, text: str) -> str:
        """Extract JSON from text, auto-close brackets, handle various formats."""
        text = text.strip()

        for start_marker in ["```json", "```javascript", "```", ""]:
            if start_marker:
                check_text = text
                if check_text.startswith(start_marker):
                    check_text = check_text[len(start_marker) :]
                    if check_text.endswith("```"):
                        check_text = check_text[:-3]
                    check_text = check_text.strip()
            else:
                check_text = text

            json_start = -1
            for char in ["{", "["]:
                pos = check_text.find(char)
                if pos != -1 and (json_start == -1 or pos < json_start):
                    json_start = pos

            if json_start == -1:
                continue

            json_part = check_text[json_start:]

            open_braces = json_part.count("{")
            close_braces = json_part.count("}")
            open_brackets = json_part.count("[")
            close_brackets = json_part.count("]")

            if close_brackets < open_brackets:
                json_part += "]" * (open_brackets - close_brackets)
            if close_braces < open_braces:
                json_part += "}" * (open_braces - close_braces)

            try:
                json.loads(json_part)
                return json_part
            except json.JSONDecodeError:
                continue

        return text


def create_provider() -> LLMProvider:
    """Factory function to create the configured LLM provider."""
    provider_name = os.getenv("LLM_PROVIDER", "openrouter").lower()
    model = os.getenv("LLM_MODEL", "openai/gpt-4o")

    if provider_name == "openrouter":
        print(f"{CLI_GREEN}Using OpenRouter provider with model: {model}{CLI_CLR}")
        return OpenRouterProvider(model=model)
    elif provider_name == "manual":
        return ManualProvider()
    elif provider_name == "opencode":
        return OpencodeProvider()
    else:
        raise ValueError(
            f"Unknown LLM_PROVIDER: {provider_name}. Use 'openrouter', 'manual', or 'opencode'."
        )
