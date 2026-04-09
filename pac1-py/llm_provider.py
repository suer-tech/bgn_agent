import json
import os
import subprocess
import time
from typing import Any, Dict, List, Type, TypeVar

from openai import OpenAI
from pydantic import BaseModel

from agents.types import NextStep

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


class LLMProvider:
    """Base class for LLM providers."""

    def complete(self, messages: List[Dict[str, Any]]) -> NextStep:
        raise NotImplementedError

    def complete_as(self, messages: List[Dict[str, Any]], response_type: Type[T]) -> T:
        raise NotImplementedError

    def _extract_json(self, text: str) -> str:
        """Extract JSON from text, auto-close brackets, handle various formats."""
        text = text.strip()

        for start_marker in ["```json", "```javascript", "```", ""]:
            check_text = text
            if start_marker:
                if check_text.startswith(start_marker):
                    check_text = check_text[len(start_marker) :]
                    if check_text.endswith("```"):
                        check_text = check_text[:-3]
                    check_text = check_text.strip()

            json_start = -1
            for char in ["{", "["]:
                pos = check_text.find(char)
                if pos != -1 and (json_start == -1 or pos < json_start):
                    json_start = pos

            if json_start == -1:
                continue

            json_part = check_text[json_start:]

            # Try to find the last closing brace/bracket that matches
            # This is more robust than just counting total braces
            try:
                # Simplest case: it's already valid JSON
                json.loads(json_part)
                return json_part
            except json.JSONDecodeError:
                pass

            # Fallback: counting braces (less safe but covers some truncated cases)
            open_braces = json_part.count("{")
            close_braces = json_part.count("}")
            open_brackets = json_part.count("[")
            close_brackets = json_part.count("]")

            temp_json = json_part
            if close_brackets < open_brackets:
                temp_json += "]" * (open_brackets - close_brackets)
            if close_braces < open_braces:
                temp_json += "}" * (open_braces - close_braces)

            try:
                json.loads(temp_json)
                return temp_json
            except json.JSONDecodeError:
                continue

        return text


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
        schema_hint = build_schema_hint_for_type(response_type)
        messages_with_schema = messages + [{"role": "system", "content": schema_hint}]

        max_retries = 10
        for attempt in range(max_retries):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages_with_schema,
                    max_tokens=16384,
                )
            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "rate" in err_str.lower():
                    wait = min(30 * (2**attempt), 300)
                    print(
                        f"{CLI_YELLOW}[Retry {attempt + 1}/{max_retries}] Rate limited, waiting {wait}s...{CLI_CLR}",
                        flush=True,
                    )
                    time.sleep(wait)
                    continue
                raise

            error = getattr(resp, "error", None)
            if error:
                err_msg = str(error)
                if "429" in err_msg or "rate" in err_msg.lower():
                    wait = min(30 * (2**attempt), 300)
                    print(
                        f"{CLI_YELLOW}[Retry {attempt + 1}/{max_retries}] Rate limited (error field), waiting {wait}s...{CLI_CLR}",
                        flush=True,
                    )
                    time.sleep(wait)
                    continue
                raise ValueError(f"LLM returned error: {error}")

            if resp.choices is None or len(resp.choices) == 0:
                wait = min(30 * (2**attempt), 300)
                print(
                    f"{CLI_YELLOW}[Retry {attempt + 1}/{max_retries}] Empty choices, waiting {wait}s...{CLI_CLR}",
                    flush=True,
                )
                time.sleep(wait)
                continue

            choice = resp.choices[0].message
            text = choice.content

            if text is None:
                tool_calls = getattr(choice, "tool_calls", None)
                if tool_calls:
                    text = tool_calls[0].function.arguments
                else:
                    reasoning = getattr(choice, "reasoning", None)
                    if reasoning:
                        text = reasoning
                    else:
                        raise ValueError(
                            f"LLM returned None content. Full choice: {choice}"
                        )

            print(
                f"{CLI_DIM}Raw LLM text ({len(text)} chars): {text[:300]}...{CLI_CLR}",
                flush=True,
            )
            json_text = self._extract_json(text)
            print(
                f"{CLI_DIM}Extracted JSON ({len(json_text)} chars): {json_text[:300]}...{CLI_CLR}",
                flush=True,
            )
            data = json.loads(json_text)
            return response_type.model_validate(data)

        raise ValueError(f"LLM rate limited after {max_retries} retries")


class AntigravityProvider(LLMProvider):
    def complete(self, messages: List[Dict[str, Any]]) -> NextStep:
        return self.complete_as(messages, NextStep)

    def complete_as(self, messages: List[Dict[str, Any]], response_type: Type[T]) -> T:
        import json, os, time

        task_id = os.environ.get("PAC1_TASK_ID", "")
        suffix = f"_{task_id}" if task_id else ""
        req_file = f".llm_request{suffix}.json"
        res_file = f".llm_response{suffix}.json"

        # 1. Clean up old files to ensure we don't read stale data
        if os.path.exists(req_file):
            os.remove(req_file)
        if os.path.exists(res_file):
            os.remove(res_file)

        # 2. Write new request
        print(
            f"\x1b[33m[Antigravity] Writing messages to {req_file}... (Size: {len(str(messages))} chars)\x1b[0m",
            flush=True,
        )
        with open(req_file, "w", encoding="utf-8") as f:
            json.dump(messages, f, indent=2, ensure_ascii=False)

        print(
            f"\x1b[33m[Antigravity] Prompt written. Waiting for {res_file}... Go to that file and provide JSON response.\x1b[0m",
            flush=True,
        )

        # 3. Wait for response file to be created
        while not os.path.exists(res_file):
            time.sleep(1)

        # 4. Wait a bit more to ensure file write is finished and try to parse
        MAX_RETRIES = 5
        data = None
        for i in range(MAX_RETRIES):
            try:
                time.sleep(0.5)
                if not os.path.exists(res_file):
                    continue
                with open(res_file, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if not content:
                        continue
                    data = json.loads(content)
                    break
            except (json.JSONDecodeError, IOError) as e:
                if i == MAX_RETRIES - 1:
                    print(f"Final attempt to parse JSON failed: {e}")
                    raise
                print(f"Attempt {i + 1} to parse {res_file} failed, retrying...")

        # 5. Clean up and return
        if os.path.exists(res_file):
            os.remove(res_file)
        if data is None:
            raise ValueError(f"Failed to read valid JSON from {res_file}")

        # Robust parsing for human-provided JSON (might have markdown)
        if isinstance(data, str):
            data = json.loads(self._extract_json(data))
        elif isinstance(data, dict):
            # Already a dict, good
            pass

        return response_type.model_validate(data)


class ClaudeCodeProvider(LLMProvider):
    """Provider that calls the claude CLI (Claude Code) as a subprocess.

    Uses the user's existing Claude Max/Pro subscription — no separate API key needed.
    Invokes `claude -p` with JSON output and parses the result.
    """

    def __init__(self, model: str = ""):
        self.model = model
        print(f"{CLI_GREEN}Using Claude Code provider (claude CLI){CLI_CLR}")

    def complete(self, messages: List[Dict[str, Any]]) -> NextStep:
        return self.complete_as(messages, NextStep)

    def complete_as(self, messages: List[Dict[str, Any]], response_type: Type[T]) -> T:
        full_prompt = messages_to_prompt(messages)
        schema_hint = build_schema_hint_for_type(response_type)
        full_prompt = full_prompt + "\n\n=== RESPONSE FORMAT ===\n" + schema_hint

        print(f"{CLI_DIM}Calling claude CLI ({len(full_prompt)} chars)...{CLI_CLR}")

        cmd = [
            "claude", "-p",
            "--output-format", "json",
            "--tools", "",
            "--system-prompt", "You are a pure JSON generator. Read the prompt and respond ONLY with a valid JSON object matching the requested schema. No commentary, no markdown fences, no explanation.",
        ]
        if self.model:
            cmd.extend(["--model", self.model])

        max_retries = 3
        for attempt in range(max_retries):
            try:
                result = subprocess.run(
                    cmd,
                    input=full_prompt.encode("utf-8"),
                    capture_output=True,
                    timeout=300,
                )
                stdout = result.stdout.decode("utf-8", errors="replace")
                stderr = result.stderr.decode("utf-8", errors="replace")

                if result.returncode != 0:
                    print(f"{CLI_RED}claude CLI error (rc={result.returncode}): {stderr[:500]}{CLI_CLR}")
                    if attempt < max_retries - 1:
                        wait = 5 * (attempt + 1)
                        print(f"{CLI_YELLOW}[Retry {attempt + 1}/{max_retries}] Waiting {wait}s...{CLI_CLR}")
                        time.sleep(wait)
                        continue
                    raise ValueError(f"claude CLI failed: {stderr[:500]}")

                # Parse the JSON envelope from claude CLI
                try:
                    envelope = json.loads(stdout)
                    text_response = envelope.get("result", "")
                except json.JSONDecodeError:
                    # Fallback: treat stdout as raw text
                    text_response = stdout

                if not text_response:
                    raise ValueError("Empty response from claude CLI")

                print(
                    f"{CLI_DIM}Claude response ({len(text_response)} chars): {text_response[:300]}...{CLI_CLR}",
                    flush=True,
                )

                json_text = self._extract_json(text_response)
                data = json.loads(json_text)
                return response_type.model_validate(data)

            except subprocess.TimeoutExpired:
                if attempt < max_retries - 1:
                    print(f"{CLI_YELLOW}[Retry {attempt + 1}/{max_retries}] Timeout, retrying...{CLI_CLR}")
                    continue
                raise ValueError("claude CLI timed out after 300 seconds")
            except (json.JSONDecodeError, Exception) as e:
                if attempt < max_retries - 1 and "timed out" not in str(e):
                    print(f"{CLI_YELLOW}[Retry {attempt + 1}/{max_retries}] Error: {e}, retrying...{CLI_CLR}")
                    time.sleep(3)
                    continue
                raise

        raise ValueError(f"claude CLI failed after {max_retries} retries")


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

        return "\n".join(combined_text)


def create_provider() -> LLMProvider:
    """Factory function to create the configured LLM provider."""
    provider_name = os.getenv("LLM_PROVIDER", "openrouter").lower()
    model = os.getenv("LLM_MODEL", "openai/gpt-4.1-mini")

    if provider_name == "openrouter":
        print(f"{CLI_GREEN}Using OpenRouter provider with model: {model}{CLI_CLR}")
        return OpenRouterProvider(model=model)
    elif provider_name == "antigravity":
        print(f"{CLI_GREEN}Using Antigravity (human-in-the-loop) provider{CLI_CLR}")
        return AntigravityProvider()
    elif provider_name == "claude":
        print(f"{CLI_GREEN}Using Claude Code provider (model: {model or 'default'}){CLI_CLR}")
        return ClaudeCodeProvider(model=model)
    elif provider_name == "opencode":
        return OpencodeProvider()
    else:
        raise ValueError(
            f"Unknown LLM_PROVIDER: {provider_name}. Use 'openrouter', 'claude', 'antigravity', or 'opencode'."
        )
