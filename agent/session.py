"""The Granite judgment agent — a strict tool-calling loop over watsonx.ai.

Architecture: the tool loop (dispatch + validation) is decoupled from the model
call. `AgentLoop` drives any `complete(messages, tools) -> assistant_message`
callable; `WatsonxClient` is the production backend (proven watsonx REST API);
tests inject a scripted model. This keeps the safety-critical loop logic testable
offline while the live model is a thin, swappable layer.

The loop enforces the core principle: the model only ever *calls tools* to get
numbers and *composes prose* to explain them. Every tool result is observed by
the validator; the final prose is validated before it reaches the operator.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from agent.prompts import build_messages
from agent.tools import TOOL_SCHEMAS, AgentTools, ToolContext
from agent.validator import Validator

IAM_TOKEN_URL = "https://iam.cloud.ibm.com/identity/token"
DEFAULT_REGION = "us-south"
DEFAULT_MODEL = "ibm/granite-4-h-small"  # verified 2026-07-24: function-calling, available
FALLBACK_MODEL = "ibm/granite-3-1-8b-base"


def _load_env() -> None:
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def parse_tool_arguments(raw) -> dict:
    """Parse a model's tool arguments, tolerating Granite's double-encoding."""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, str):  # double-encoded JSON string
            parsed = json.loads(parsed)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


@dataclass
class AgentResponse:
    content: str  # validated prose shown to the operator
    messages: list[dict] = field(default_factory=list)  # full transcript
    tool_calls_made: list[str] = field(default_factory=list)
    audit_passed: bool = True


class WatsonxClient:
    """Thin client for the watsonx.ai chat + tool-calling REST API."""

    def __init__(
        self,
        api_key: str | None = None,
        project_id: str | None = None,
        region: str | None = None,
        model_id: str | None = None,
    ):
        _load_env()
        self.api_key = api_key or os.environ.get("WATSONX_APIKEY", "")
        self.project_id = project_id or os.environ.get("WATSONX_PROJECT_ID", "")
        self.region = region or os.environ.get("WATSONX_REGION", DEFAULT_REGION)
        self.model_id = model_id or os.environ.get("WATSONX_MODEL_ID", DEFAULT_MODEL)
        self._token: str | None = None

    def _get_token(self, client: httpx.Client) -> str:
        if self._token:
            return self._token
        resp = client.post(
            IAM_TOKEN_URL,
            data={"grant_type": "urn:ibm:params:oauth:grant-type:apikey", "apikey": self.api_key},
        )
        resp.raise_for_status()
        self._token = resp.json()["access_token"]
        return self._token

    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        """One chat completion. Returns the assistant message (content and/or tool_calls)."""
        url = f"https://{self.region}.ml.cloud.ibm.com/ml/v1/text/chat?version=2024-03-14"
        payload = {
            "model_id": self.model_id,
            "project_id": self.project_id,
            "messages": messages,
            "tools": tools,
            "parameters": {"max_new_tokens": 1024, "temperature": 0},
        }
        with httpx.Client(timeout=120.0) as client:
            token = self._get_token(client)
            resp = client.post(url, json=payload, headers={"Authorization": f"Bearer {token}"})
            resp.raise_for_status()
            data = resp.json()
        choice = data["choices"][0]["message"]
        return {
            "role": "assistant",
            "content": choice.get("content"),
            "tool_calls": choice.get("tool_calls"),
        }


class AgentLoop:
    """Model-agnostic tool-calling loop with validation."""

    def __init__(self, tools: AgentTools, validator: Validator, complete):
        self.tools = tools
        self.validator = validator
        self.complete = complete  # callable(messages, tools) -> assistant message

    def run(self, user_message: str, max_iterations: int = 8) -> AgentResponse:
        messages = build_messages(user_message)
        tool_calls_made: list[str] = []
        # The operator's stated constraints (fuel margin, required miss, etc.) are
        # legitimate for the model to restate — seed them into the truth set.
        self.validator.observe_text(user_message)

        for _ in range(max_iterations):
            assistant = self.complete(messages, TOOL_SCHEMAS)
            messages.append(assistant)
            tool_calls = assistant.get("tool_calls")

            if not tool_calls:
                content = assistant.get("content") or ""
                validated = self.validator.validate_prose(content)
                return AgentResponse(
                    content=validated,
                    messages=messages,
                    tool_calls_made=tool_calls_made,
                    audit_passed=self.validator.all_passed,
                )

            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                args = parse_tool_arguments(fn.get("arguments"))
                self.validator.observe_arguments(args)  # the model's own values are legitimate
                result = self.tools.dispatch(name, args)
                self.validator.observe([result])
                tool_calls_made.append(name)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": json.dumps(result),
                    }
                )

        return AgentResponse(
            content="(reached the tool-call limit without a final answer)",
            messages=messages,
            tool_calls_made=tool_calls_made,
            audit_passed=self.validator.all_passed,
        )

    def run_stream(self, user_message: str, max_iterations: int = 8):
        """Yield events as the loop progresses — for SSE streaming.

        Events: {"type": "tool_call", "name", "arguments"},
                {"type": "tool_result", "name", "result"},
                {"type": "content", "text"},
                {"type": "done", "audit_passed"}.
        """
        messages = build_messages(user_message)
        self.validator.observe_text(user_message)

        for _ in range(max_iterations):
            assistant = self.complete(messages, TOOL_SCHEMAS)
            messages.append(assistant)
            tool_calls = assistant.get("tool_calls")

            if not tool_calls:
                content = assistant.get("content") or ""
                validated = self.validator.validate_prose(content)
                yield {"type": "content", "text": validated}
                yield {"type": "done", "audit_passed": self.validator.all_passed}
                return

            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                args = parse_tool_arguments(fn.get("arguments"))
                yield {"type": "tool_call", "name": name, "arguments": args}
                self.validator.observe_arguments(args)
                result = self.tools.dispatch(name, args)
                self.validator.observe([result])
                messages.append(
                    {"role": "tool", "tool_call_id": tc.get("id", ""), "content": json.dumps(result)}
                )
                yield {"type": "tool_result", "name": name, "result": result}

        yield {"type": "content", "text": "(reached the tool-call limit without a final answer)"}
        yield {"type": "done", "audit_passed": self.validator.all_passed}


class OrbitWardenAgent:
    """Ties the tool context, validator, loop, and watsonx backend together."""

    def __init__(self, ctx: ToolContext, client: WatsonxClient | None = None):
        self.ctx = ctx
        self.tools = AgentTools(ctx)
        self.validator = Validator()
        self.client = client or WatsonxClient()
        self.loop = AgentLoop(self.tools, self.validator, self.client.complete)

    def chat(self, user_message: str, max_iterations: int = 8) -> AgentResponse:
        return self.loop.run(user_message, max_iterations=max_iterations)
