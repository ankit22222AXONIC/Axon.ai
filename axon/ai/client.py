"""AXON OpenRouter AI client — handles API communication with OpenRouter."""

import json
import os
import urllib.request
import urllib.error
from typing import Optional, List, Dict, Any, Callable, Tuple


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-4o-mini"


class AIClientError(Exception):
    """Raised when communication with the AI API fails."""
    pass


class OpenRouterClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 30,
        transport_fn: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        fallback_api_key: Optional[str] = None,
    ):
        if api_key is not None:
            self._api_key = api_key.strip()
        else:
            self._api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        self.model = model or os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL).strip()
        self.base_url = (base_url if base_url is not None else os.environ.get("OPENROUTER_BASE_URL", "")).strip() or OPENROUTER_BASE_URL
        self.timeout = timeout
        self.max_retries = int(os.environ.get("OPENROUTER_MAX_RETRIES", 3))
        self._transport_fn = transport_fn
        self.fallback_api_key = fallback_api_key.strip() if fallback_api_key else os.environ.get("OPENROUTER_FALLBACK_API_KEY", "").strip()
        self._primary_api_key = self._api_key
        self._fallback_date_ist = None

    @property
    def provider_name(self) -> str:
        if "googleapis" in self.base_url:
            return "Gemini"
        elif "openrouter" in self.base_url:
            return "OpenRouter"
        return "AI Provider"

    @property
    def has_api_key(self) -> bool:
        return bool(self._api_key and self._api_key != "PASTE_YOUR_OPENROUTER_KEY_HERE")

    def update_api_key(self, api_key: str):
        """Update active and primary API key in memory."""
        clean = (api_key or "").strip()
        self._api_key = clean
        self._primary_api_key = clean

    @staticmethod
    def validate_api_key(api_key: str, timeout: int = 10) -> Tuple[bool, str]:
        """Validate an OpenRouter API key via a minimal, safe authentication request.
        
        Uses OpenRouter's key validation endpoint without spending any inference tokens.
        Returns (is_valid, message).
        """
        clean_key = (api_key or "").strip()
        if not clean_key or clean_key == "PASTE_YOUR_OPENROUTER_KEY_HERE":
            return False, "API key cannot be empty."

        headers = {
            "Authorization": f"Bearer {clean_key}",
            "HTTP-Referer": "https://github.com/axon",
            "X-Title": "AXON",
            "User-Agent": "AXON-Setup/1.0",
        }

        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/auth/key",
            headers=headers,
            method="GET",
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                if response.status == 200:
                    return True, "API key verified successfully."
                return False, f"Unexpected response status ({response.status})."
        except urllib.error.HTTPError as e:
            if e.code == 401:
                return False, "Invalid OpenRouter API key. Please check the key and try again."
            if e.code == 403:
                return False, "Access forbidden. Your OpenRouter key may have restricted permissions."
            return False, f"OpenRouter returned error (HTTP {e.code})."
        except urllib.error.URLError as e:
            return False, f"Unable to reach OpenRouter: {e.reason}"
        except TimeoutError:
            return False, "Verification timed out. Please check your network connection."
        except Exception as e:
            return False, f"Verification failed: {e}"

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Send chat messages and optional tool definitions to OpenRouter or OpenAI-compatible endpoint."""
        if not self.has_api_key:
            raise AIClientError(
                f"{self.provider_name} API key is not configured. Set the OPENROUTER_API_KEY environment variable."
            )

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": int(os.environ.get("OPENROUTER_MAX_TOKENS", 2048)),
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        if self._transport_fn:
            return self._transport_fn(payload)

        return self._send_request(payload)

    def _send_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        import time

        data_bytes = json.dumps(payload).encode("utf-8")

        # Check if we should reset to primary key (daily reset at midnight IST)
        if self._api_key != self._primary_api_key and self._fallback_date_ist:
            from datetime import datetime, timezone, timedelta
            ist = timezone(timedelta(hours=5, minutes=30))
            now_ist = datetime.now(ist).date()
            if now_ist > self._fallback_date_ist:
                print(f"\n[*] Midnight IST passed. Resetting to primary {self.provider_name} API key.")
                self._api_key = self._primary_api_key
                self._fallback_date_ist = None

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/axon",
            "X-Title": "AXON",
        }

        for attempt in range(self.max_retries):
            req = urllib.request.Request(
                self.base_url,
                data=data_bytes,
                headers=headers,
                method="POST",
            )

            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    body = response.read().decode("utf-8")
                    data = json.loads(body)

                    # Check for in-band error returned in JSON payload
                    if isinstance(data, dict) and "error" in data:
                        err_obj = data["error"]
                        msg = err_obj.get("message", "") if isinstance(err_obj, dict) else str(err_obj)
                        code = err_obj.get("code") if isinstance(err_obj, dict) else None

                        msg_lower = msg.lower()
                        is_quota = code == 402 or code == 403 or any(kw in msg_lower for kw in [
                            "insufficient quota", "limit exceeded", "out of credits", "balance", "credit limit"
                        ])

                        if is_quota and self.fallback_api_key and self._api_key != self.fallback_api_key:
                            print(f"\n[!] Primary {self.provider_name} API key exhausted limits. Switching to fallback key.")
                            from datetime import datetime, timezone, timedelta
                            self._api_key = self.fallback_api_key
                            self._fallback_date_ist = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
                            headers["Authorization"] = f"Bearer {self._api_key}"
                            continue

                        is_transient = any(kw in msg_lower for kw in [
                            "overloaded", "rate limit", "temporarily", "unavailable",
                            "try again", "timeout", "busy", "capacity", "provider", "upstream",
                        ]) or code in (429, 500, 502, 503, 504)

                        if is_transient and attempt < self.max_retries - 1:
                            time.sleep(max(2.0, (2 ** attempt) * 2.0))
                            continue

                        raise AIClientError(f"{self.provider_name} API error ({code or 'provider'}): {msg}")

                    # Check if choices is empty without error
                    if isinstance(data, dict) and "choices" in data and not data["choices"]:
                        if attempt < self.max_retries - 1:
                            time.sleep(max(2.0, (2 ** attempt) * 2.0))
                            continue

                    return data

            except urllib.error.HTTPError as e:
                error_body = ""
                try:
                    error_body = e.read().decode("utf-8")
                    error_json = json.loads(error_body)
                    msg = error_json.get("error", {}).get("message", error_body)
                except Exception:
                    msg = error_body or str(e)

                if e.code in (402, 403) and self.fallback_api_key and self._api_key != self.fallback_api_key:
                    print(f"\n[!] Primary {self.provider_name} API key exhausted limits (HTTP {e.code}). Switching to fallback key.")
                    from datetime import datetime, timezone, timedelta
                    self._api_key = self.fallback_api_key
                    self._fallback_date_ist = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
                    headers["Authorization"] = f"Bearer {self._api_key}"
                    continue

                if e.code in (429, 500, 502, 503, 504) and attempt < self.max_retries - 1:
                    retry_after = e.headers.get("Retry-After")
                    sleep_time = float(retry_after) if retry_after and retry_after.isdigit() else max(2.0, (2 ** attempt) * 2.5)
                    time.sleep(sleep_time)
                    continue

                raise AIClientError(f"{self.provider_name} API error (HTTP {e.code}): {msg}") from None
            except urllib.error.URLError as e:
                if attempt < self.max_retries - 1:
                    time.sleep(max(1.5, (2 ** attempt) * 1.5))
                    continue
                raise AIClientError(f"Network error connecting to {self.provider_name}: {e.reason}") from None
            except TimeoutError:
                if attempt < self.max_retries - 1:
                    time.sleep(max(1.5, (2 ** attempt) * 1.5))
                    continue
                raise AIClientError(f"Request to {self.provider_name} timed out after {self.timeout}s.") from None
            except json.JSONDecodeError:
                if attempt < self.max_retries - 1:
                    time.sleep(max(1.5, (2 ** attempt) * 1.5))
                    continue
                raise AIClientError(f"Failed to parse response from {self.provider_name}.") from None
            except AIClientError:
                raise
            except Exception as e:
                raise AIClientError(f"Unexpected error communicating with {self.provider_name}: {e}") from None

        raise AIClientError(f"{self.provider_name} request failed after maximum retries.")
