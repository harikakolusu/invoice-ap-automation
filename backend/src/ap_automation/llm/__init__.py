"""LLM features (Claude via the official Anthropic SDK): extraction fallback, exception copilot, benchmark.

Optional: without the SDK or an API key, every LLM entry point raises LLMUnavailable and the deterministic
pipeline keeps working unchanged.
"""
from .client import Claude, LLMError, LLMUnavailable, status

__all__ = ["Claude", "LLMError", "LLMUnavailable", "status"]
