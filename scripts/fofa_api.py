"""FOFA API layer — HTTP client with rate limiting, retry, and F-point guard.

Features
--------
- Rate limiting: >= 1 s between requests (FOFA limit for personal/pro tiers).
- Retry: exponential backoff on 429 (Too Many Requests), up to 3 retries.
- F-point guard: page > 1 is blocked unless ``allow_fpoints=True``.
- Business error handling: detects FOFA API errors in HTTP 200 responses.
- All functions return plain dicts (decoded JSON or error envelope).

Uses only Python stdlib (urllib, base64, json, time).
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

BASE_URL: str = os.environ.get("FOFA_BASE_URL", "https://fofa.info/api/v1")

_last_request_time: float = 0.0
MIN_INTERVAL: float = 1.0
MAX_RETRIES: int = 3
TIMEOUT: int = 30


def _rate_limit() -> None:
    """Ensure at least MIN_INTERVAL seconds between requests."""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    _last_request_time = time.time()


def _check_business_error(data: Any) -> Optional[Dict[str, Any]]:
    """Check for FOFA business-level errors in HTTP 200 responses.

    FOFA API sometimes returns HTTP 200 with an error in the JSON body:
    - ``{"errmsg": "some error", ...}``  (search/info errors)
    - ``{"error": true, "errmsg": "..."}``  (some endpoints)
    - ``{"error": -1, "errmsg": "..."}``  (numeric error code)

    Returns an error envelope dict if a business error is detected, else None.
    """
    if not isinstance(data, dict):
        return None

    errmsg = data.get("errmsg")
    error_flag = data.get("error")

    # FOFA returns errmsg as a non-empty/non-zero string on business errors
    has_errmsg = errmsg is not None and errmsg is not False and errmsg != 0 and errmsg != "0"

    # Some endpoints use "error": true or "error": -1
    has_error_flag = error_flag is True or (isinstance(error_flag, int) and error_flag < 0)

    if has_errmsg or has_error_flag:
        msg = str(errmsg) if errmsg else "Unknown FOFA API business error"
        # Map known FOFA error codes to our code ranges
        fofa_code = data.get("code")
        if isinstance(fofa_code, int) and fofa_code > 0:
            # 90001 = invalid key, 90002 = not VIP, etc.
            if fofa_code in (90001, 90002):
                return {"error": True, "msg": f"FOFA API [{fofa_code}]: {msg}", "code": 1002}
            elif fofa_code == 90003:
                return {"error": True, "msg": f"FOFA API [{fofa_code}]: {msg}", "code": 2002}
        return {"error": True, "msg": f"FOFA API: {msg}", "code": 1001}

    return None


def _request(url: str, retries: int = MAX_RETRIES) -> Dict[str, Any]:
    """Perform a GET request with retry on 429 / network errors."""
    for attempt in range(retries + 1):
        _rate_limit()
        try:
            req = urllib.request.Request(url)
            req.add_header("Accept", "application/json")
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                body = resp.read().decode("utf-8")
                data = json.loads(body)
                # Check FOFA business-level errors (HTTP 200 but API error)
                biz_err = _check_business_error(data)
                if biz_err is not None:
                    return biz_err
                return data
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries:
                time.sleep(2 ** attempt)
                continue
            # Try to extract FOFA error message from response body
            try:
                err_body = e.read().decode("utf-8")
                err_data = json.loads(err_body)
                err_msg = err_data.get("errmsg", f"HTTP {e.code}: {e.reason}")
                return {"error": True, "msg": f"FOFA API: {err_msg}", "code": 1001}
            except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
                return {"error": True, "msg": f"HTTP {e.code}: {e.reason}", "code": 1001}
        except urllib.error.URLError as e:
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue
            return {"error": True, "msg": str(e.reason), "code": 1004}
    # Safety fallback
    return {"error": True, "msg": "max retries exceeded", "code": 1001}


def _check_fpoints(page: int, allow_fpoints: bool) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Return (ok, error_dict)."""
    if page <= 1:
        return True, None
    if not allow_fpoints:
        return False, {
            "error": True,
            "msg": "F-point spend denied: pagination requires F-points. Explicitly authorize and retry.",
            "code": 2001,
        }
    return True, None


def _normalize_host_response(data: Dict[str, Any], detail: bool) -> Dict[str, Any]:
    """Normalize host API response to a consistent structure.

    FOFA host API returns different structures:
    - Without detail: flat object with host, ip, asn, org, country_name, port, protocol
    - With detail: same flat fields PLUS per-port detail arrays

    We ensure the response always has a consistent top-level structure.
    """
    # Ensure essential fields exist with defaults
    result: Dict[str, Any] = {}
    for key in ("host", "ip", "asn", "org", "country_name", "country_code",
                "port", "protocol", "domain", "os"):
        if key in data:
            result[key] = data[key]

    if detail:
        # With --detail, FOFA may return per-port details in various formats
        # Normalize into a "details" list
        if "detail" in data and isinstance(data["detail"], list):
            result["details"] = data["detail"]
        elif "results" in data and isinstance(data["results"], list):
            result["details"] = data["results"]
        else:
            # Extract detail from any extra fields not in the standard set
            extra = {k: v for k, v in data.items() if k not in result}
            if extra:
                result["details"] = [extra]

    return result


# ------------------------------------------------------------------ public API


def search(
    key: str,
    query: str,
    fields: str = "ip,port,protocol,host,domain,title,server",
    page: int = 1,
    size: int = 100,
    full: bool = False,
    allow_fpoints: bool = False,
) -> Dict[str, Any]:
    """Search FOFA's database. Returns API response dict or error envelope."""
    ok, err = _check_fpoints(page, allow_fpoints)
    if not ok:
        return err  # type: ignore[return-value]

    qbase64 = base64.b64encode(query.encode()).decode()
    params = urllib.parse.urlencode({
        "key": key, "qbase64": qbase64,
        "fields": fields, "page": page, "size": size,
        "full": str(full).lower(),
    })
    return _request(f"{BASE_URL}/search/all?{params}")


def get_info(key: str) -> Dict[str, Any]:
    """Get account info (free — no F-point cost)."""
    params = urllib.parse.urlencode({"key": key})
    return _request(f"{BASE_URL}/info/my?{params}")


def stats(key: str, query: str, field: str) -> Dict[str, Any]:
    """Statistical aggregation for a query.

    The ``field`` parameter supports comma-separated values for multi-field
    aggregation (e.g. ``country,port``). FOFA API uses ``fields`` parameter
    for the aggregation dimension(s).
    """
    qbase64 = base64.b64encode(query.encode()).decode()
    params = urllib.parse.urlencode({
        "key": key, "qbase64": qbase64, "fields": field,
    })
    return _request(f"{BASE_URL}/search/stats?{params}")


def host(key: str, host_ip: str, detail: bool = False) -> Dict[str, Any]:
    """Get detailed information about a specific host.

    Response structure varies based on ``detail``:
    - Without detail: flat object (host, ip, asn, org, country_name, port, protocol)
    - With detail: adds a ``details`` list with per-port protocol/banner/cert info
    """
    params = urllib.parse.urlencode({"key": key, "detail": str(detail).lower()})
    resp = _request(f"{BASE_URL}/host/{urllib.parse.quote(host_ip, safe='')}?{params}")
    if resp.get("error"):
        return resp
    return _normalize_host_response(resp, detail)
