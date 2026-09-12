"""Secret and credential redaction layer."""

import re
from typing import Any, Tuple, List


# Secret detection regular expressions
SECRET_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # Private Key blocks
    (
        re.compile(r"-----BEGIN\s+[A-Z0-9\s_-]+PRIVATE\s+KEY-----[\s\S]*?-----END\s+[A-Z0-9\s_-]+PRIVATE\s+KEY-----", re.MULTILINE),
        "[REDACTED_PRIVATE_KEY]"
    ),
    # OpenAI / OpenRouter / Anthropic API keys
    (
        re.compile(r"\b(sk-[a-zA-Z0-9_-]{20,})\b"),
        "[REDACTED_API_KEY]"
    ),
    (
        re.compile(r"\b(sk-or-v1-[a-f0-9]{64})\b", re.IGNORECASE),
        "[REDACTED_API_KEY]"
    ),
    (
        re.compile(r"\b(sk-ant-[a-zA-Z0-9_-]{20,})\b"),
        "[REDACTED_API_KEY]"
    ),
    # AWS Access Key ID
    (
        re.compile(r"\b(AKIA[0-9A-Z]{16})\b"),
        "[REDACTED_AWS_KEY]"
    ),
    # GitHub Personal Access Token
    (
        re.compile(r"\b(ghp_[a-zA-Z0-9]{36})\b"),
        "[REDACTED_GITHUB_TOKEN]"
    ),
    (
        re.compile(r"\b(github_pat_[a-zA-Z0-9_]{50,})\b"),
        "[REDACTED_GITHUB_TOKEN]"
    ),
    # Authorization: Bearer tokens
    (
        re.compile(r"(Bearer\s+)([a-zA-Z0-9_\-\.]{25,})", re.IGNORECASE),
        r"\1[REDACTED_BEARER_TOKEN]"
    ),
    # Common secret/password assignments in text
    (
        re.compile(r"(?i)\b((?:api_key|apikey|secret_key|private_key|auth_token|password|passwd)\s*[:=]\s*['\"]?)([^'\"\s\r\n]{8,})(['\"]?)"),
        r"\1[REDACTED_SECRET]\3"
    ),
]


def redact_text(text: str) -> Tuple[str, bool]:
    """Scan and redact known secret patterns from a string.
    
    Returns:
        (sanitized_text, was_redacted)
    """
    if not text or not isinstance(text, str):
        return text, False

    modified = False
    result = text
    for pattern, replacement in SECRET_PATTERNS:
        new_result, count = pattern.subn(replacement, result)
        if count > 0:
            modified = True
            result = new_result

    return result, modified


def redact_secrets(data: Any) -> Tuple[Any, bool]:
    """Recursively redact secrets from arbitrary data structures (dict, list, string).
    
    Returns:
        (sanitized_data, was_redacted)
    """
    if isinstance(data, str):
        return redact_text(data)

    if isinstance(data, dict):
        modified_any = False
        clean_dict = {}
        for k, v in data.items():
            # If key name strongly indicates a secret, redact entirely if it's a string
            if isinstance(k, str) and any(s in k.lower() for s in ("password", "secret", "api_key", "token", "private_key")):
                if isinstance(v, str) and len(v) > 0:
                    clean_dict[k] = "[REDACTED_SECRET]"
                    modified_any = True
                    continue
            clean_v, was_mod = redact_secrets(v)
            if was_mod:
                modified_any = True
            clean_dict[k] = clean_v
        return clean_dict, modified_any

    if isinstance(data, list):
        modified_any = False
        clean_list = []
        for item in data:
            clean_item, was_mod = redact_secrets(item)
            if was_mod:
                modified_any = True
            clean_list.append(clean_item)
        return clean_list, modified_any

    return data, False
