"""Model text with content-free completion metadata for citation diagnostics."""


class ModelOutput(str):
    def __new__(cls, text: str, *, output_tokens: object, token_limit: int, finish_reason: object):
        value = super().__new__(cls, text)
        tokens = output_tokens if type(output_tokens) is int else None
        reason = finish_reason if finish_reason in ("stop", "length", "load", "unload", "tool_calls", "content_filter") else "unknown"
        value.completion_metadata = {
            "output_tokens": tokens,
            "output_token_limit": token_limit,
            "finish_reason": reason,
            "truncated": reason == "length" or (tokens is not None and tokens >= token_limit),
            "response_characters": len(text),
        }
        return value
