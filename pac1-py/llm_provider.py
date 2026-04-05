import json
import os
import subprocess
from typing import Any, Dict, List, Type, TypeVar

from openai import OpenAI
from pydantic import BaseModel

from agents.types import NextStep

T = TypeVar("T", bound=BaseModel)

# ANSI colors
CLI_RED = "\x1b[31m"
CLI_YELLOW = "\x1B[33m"
CLI_GREEN = "\x1B[32m"
CLI_CYAN = "\x1b[36m"
CLI_CLR = "\x1B[0m"
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


class AntigravityProvider(LLMProvider):
    def complete(self, messages: List[Dict[str, Any]]) -> NextStep:
        return self.complete_as(messages, NextStep)

    def complete_as(self, messages: List[Dict[str, Any]], response_type: Type[T]) -> T:
        import json, os, time
        req_file = '.llm_request.json'
        res_file = '.llm_response.json'
        
        # 1. Clean up old files to ensure we don't read stale data
        if os.path.exists(req_file):
            os.remove(req_file)
        if os.path.exists(res_file):
            os.remove(res_file)
            
        # 2. Write new request
        print(f"\x1b[33m[Antigravity] Writing messages to {req_file}... (Size: {len(str(messages))} chars)\x1b[0m", flush=True)
        with open(req_file, 'w', encoding='utf-8') as f:
            json.dump(messages, f, indent=2, ensure_ascii=False)
            
        print(f"\x1b[33m[Antigravity] Prompt written. Waiting for {res_file}... Go to that file and provide JSON response.\x1b[0m", flush=True)
        
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
                with open(res_file, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if not content:
                        continue
                    data = json.loads(content)
                    break
            except (json.JSONDecodeError, IOError) as e:
                if i == MAX_RETRIES - 1:
                    print(f"Final attempt to parse JSON failed: {e}")
                    raise
                print(f"Attempt {i+1} to parse {res_file} failed, retrying...")
                    
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
    elif provider_name == "opencode":
        return OpencodeProvider()
    else:
        raise ValueError(
            f"Unknown LLM_PROVIDER: {provider_name}. Use 'openrouter', 'antigravity', or 'opencode'."
        )
