"""Claude client wrapper: one structured-output (JSON schema) call with clear failure modes.

- Credentials: ANTHROPIC_API_KEY from the environment or backend/.env (never hard-coded).
- Model / effort: configs/default.json -> "llm", overridable with AP_LLM_* env vars.
- Server-side refusal fallbacks are on by default (`fallbacks: "default"`).
- The client is injectable, so tests run with a fake and no network.
"""
from __future__ import annotations

import json
import os

from ..common import PROJECT_ROOT, load_config

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMUnavailable(RuntimeError):
    """SDK missing or no credentials: the feature is off, everything else keeps working."""


class LLMError(RuntimeError):
    """The call was made but did not produce a usable answer."""


def load_dotenv(path=PROJECT_ROOT / ".env") -> None:
    """Minimal .env reader (KEY=VALUE lines); real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            v = v.split(" #", 1)[0].strip().strip('"').strip("'")
            if v:
                os.environ.setdefault(k.strip(), v)


def settings() -> dict:
    load_dotenv()
    c = load_config()["llm"]
    return {"model": os.environ.get("AP_LLM_MODEL", c["model"]),
            "extraction_effort": os.environ.get("AP_LLM_EXTRACTION_EFFORT", c["extraction_effort"]),
            "copilot_effort": os.environ.get("AP_LLM_COPILOT_EFFORT", c["copilot_effort"]),
            "max_tokens": c["max_tokens"], "fallbacks": c["refusal_fallbacks"]}


def status() -> dict:
    s = settings()
    try:
        import anthropic  # noqa: F401
        sdk = True
    except ImportError:
        sdk = False
    creds = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    return {"provider": "anthropic", "model": s["model"], "sdk_installed": sdk, "credentials_configured": creds,
            "available": sdk and creds,
            "hint": None if sdk and creds else "pip install anthropic" if not sdk
            else "set ANTHROPIC_API_KEY in backend/.env (see backend/.env.example)"}


class Claude:
    """`Claude()(system, user, schema, effort)` -> (parsed JSON dict, usage dict)."""

    def __init__(self, client=None):
        self.cfg = settings()
        if client is None:
            try:
                import anthropic
            except ImportError as e:
                raise LLMUnavailable("Anthropic SDK not installed: pip install anthropic") from e
            client = anthropic.Anthropic()
        self.client = client
        self.model = self.cfg["model"]

    def __call__(self, system: str, user: str, schema: dict, effort: str) -> tuple[dict, dict]:
        import anthropic
        try:
            resp = self.client.beta.messages.create(
                model=self.model,
                max_tokens=self.cfg["max_tokens"],
                betas=[FALLBACK_BETA],
                fallbacks=self.cfg["fallbacks"],
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            )
        except anthropic.AuthenticationError as e:
            raise LLMUnavailable("Anthropic API key rejected; check ANTHROPIC_API_KEY") from e
        except anthropic.PermissionDeniedError as e:
            raise LLMUnavailable(f"API key lacks access to {self.model}") from e
        except anthropic.RateLimitError as e:
            raise LLMError("Claude rate limit reached; retry shortly") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"Claude API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LLMError("Could not reach the Claude API (network)") from e
        except TypeError as e:            # SDK raises this when no credential source resolves
            if "authentication" in str(e).lower():
                raise LLMUnavailable("No Anthropic credentials: set ANTHROPIC_API_KEY in backend/.env") from e
            raise

        if resp.stop_reason == "refusal":
            raise LLMError("Claude declined this request")
        if resp.stop_reason == "max_tokens":
            raise LLMError("Claude response was cut off (max_tokens)")
        text = next((b.text for b in resp.content if b.type == "text"), None)
        if text is None:
            raise LLMError("Claude returned no text block")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMError("Claude returned invalid JSON") from e
        usage = {"model": getattr(resp, "model", self.model),
                 "input_tokens": getattr(resp.usage, "input_tokens", None),
                 "output_tokens": getattr(resp.usage, "output_tokens", None),
                 "request_id": getattr(resp, "_request_id", None)}
        return data, usage
