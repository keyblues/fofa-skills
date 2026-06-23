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

try:
    from fofa_errors import VERSION as _VERSION
except ImportError:  # pragma: no cover - fallback for installed package
    _VERSION = "0.0.0"


def _get_version() -> str:
    return _VERSION


BASE_URL: str = os.environ.get("FOFA_BASE_URL", "https://fofa.info/api/v1")

_last_request_time: float = 0.0
MIN_INTERVAL: float = 1.0
MAX_RETRIES: int = 3
TIMEOUT: int = 30

# Session-level F-point budget (avoids per-request confirmation churn).
# Set via env FOFA_FPOINTS_BUDGET=N to allow up to N F-points per session
# without per-request AI confirmation. AI should still inform the user.
# The spent total is persisted to a state file so it accumulates across CLI
# invocations within one AI session (each `fofa_smart.py` call is its own
# process; without persistence the budget could never deplete).
_fpoints_budget: Optional[int] = None
_fpoints_budget_resolved: bool = False
_fpoints_spent: int = 0
_fpoints_state_loaded: bool = False
_FPOINTS_STATE_STALE_SEC: int = 8 * 3600


def _fpoints_state_path() -> str:
    """Path to the persisted F-point spend state file."""
    return os.environ.get(
        "FOFA_FPOINTS_STATE",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "fpoints_state.json"),
    )


def _load_fpoints_state(budget: int) -> None:
    """Load persisted spent total if budget matches and state is fresh.

    Fails open: any read/parse error or stale/foreign-budget state leaves
    ``_fpoints_spent`` at 0, which is safe (the guard then re-accumulates
    from scratch rather than trusting bad data).
    """
    global _fpoints_spent, _fpoints_state_loaded
    _fpoints_state_loaded = True
    try:
        with open(_fpoints_state_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return
    if not isinstance(data, dict) or data.get("budget") != budget:
        return  # budget changed → treat as a new session
    updated = data.get("updated", 0)
    if not isinstance(updated, (int, float)) or time.time() - updated > _FPOINTS_STATE_STALE_SEC:
        return  # stale → reset
    spent = data.get("spent", 0)
    if isinstance(spent, int) and spent >= 0:
        _fpoints_spent = spent


def _save_fpoints_state(budget: int) -> None:
    """Persist spent total so subsequent CLI invocations see it.

    Best-effort: a write failure must never block a search.
    """
    path = _fpoints_state_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"budget": budget, "spent": _fpoints_spent, "updated": time.time()}, f)
    except OSError:
        pass


def _resolve_fpoints_budget() -> Optional[int]:
    """Load session F-point budget from env (cached after first read).

    Returns the budget int, or None if unset/invalid (per-request
    authorization mode then applies). The None result is also cached.
    """
    global _fpoints_budget, _fpoints_budget_resolved
    if not _fpoints_budget_resolved:
        _fpoints_budget_resolved = True
        raw = os.environ.get("FOFA_FPOINTS_BUDGET", "")
        if raw and raw.isdigit():
            _fpoints_budget = int(raw)
    return _fpoints_budget


def get_fpoints_spent() -> int:
    """Return cumulative F-points consumed in this session."""
    return _fpoints_spent


def _rate_limit() -> None:
    """Ensure at least MIN_INTERVAL seconds between requests."""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    _last_request_time = time.time()


def _check_fpoints(page: int, allow_fpoints: bool, size: int = 100) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Return (ok, error_dict). Supports session-level budget.

    In budget mode, the estimated cost is reserved (added to ``_fpoints_spent``
    and persisted) up-front. If the request later fails, the caller MUST call
    ``_refund_fpoints(cost)`` so a network/API failure does not deplete the
    budget for FOFA charges that never happened. The reservation pattern keeps
    concurrent reservations honest under a single-process model.
    """
    global _fpoints_spent
    if page <= 1:
        return True, None

    # Estimate F-point cost for this request (page-1)*size is approximate.
    estimated_cost = (page - 1) * size

    # Session budget mode: check if within remaining budget
    budget = _resolve_fpoints_budget()
    if budget is not None:
        # Load persisted spend from prior CLI invocations in this session.
        if not _fpoints_state_loaded:
            _load_fpoints_state(budget)
        if _fpoints_spent + estimated_cost > budget:
            return False, {
                "error": True,
                "msg": f"F-point budget exceeded: session budget {budget}, already spent {_fpoints_spent}, "
                       f"this request needs ~{estimated_cost}. Ask user to raise FOFA_FPOINTS_BUDGET.",
                "code": 2001,
            }
        _fpoints_spent += estimated_cost
        _save_fpoints_state(budget)
        return True, None

    # Per-request authorization mode (original behavior)
    if not allow_fpoints:
        return False, {
            "error": True,
            "msg": "F-point spend denied: pagination requires F-points. Explicitly authorize and retry.",
            "code": 2001,
        }
    return True, None


def _refund_fpoints(cost: int) -> None:
    """Refund a previously reserved F-point cost when the request failed.

    No-op outside budget mode or for non-positive cost. Safe to call even if
    no reservation was made (e.g. page=1, which never reserves).
    """
    global _fpoints_spent
    if cost <= 0:
        return
    budget = _resolve_fpoints_budget()
    if budget is None:
        return  # per-request mode tracks no spend
    _fpoints_spent = max(0, _fpoints_spent - cost)
    _save_fpoints_state(budget)


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

    # FOFA returns errmsg as a non-empty string on business errors.
    # 注意：空字符串 "" 和 "0" 不应被视为错误（正常响应可能包含这些值）。
    has_errmsg = isinstance(errmsg, str) and errmsg != "" and errmsg != "0"
    # 某些接口用非零数字表示错误码
    if isinstance(errmsg, int) and errmsg != 0:
        has_errmsg = True

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
        # F 点余额不足：FOFA 错误码不固定，基于 msg 关键词识别
        # 映射到 2003 (QUOTA_EXCEEDED)，与 SKILL.md 定义一致
        if any(kw in msg for kw in ("余额不足", "F点不足", "F-coin", "insufficient")):
            return {"error": True, "msg": f"FOFA API: {msg}", "code": 2003}
        return {"error": True, "msg": f"FOFA API: {msg}", "code": 1001}

    return None


def _request(url: str, retries: int = MAX_RETRIES) -> Dict[str, Any]:
    """Perform a GET request with retry on 429 / network errors."""
    for attempt in range(retries + 1):
        _rate_limit()
        try:
            req = urllib.request.Request(url)
            req.add_header("Accept", "application/json")
            req.add_header("User-Agent", f"fofa-skills/{_get_version()}")
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                body = resp.read().decode("utf-8")
                try:
                    data = json.loads(body)
                except json.JSONDecodeError:
                    preview = body[:200].replace("\n", " ")
                    return {
                        "error": True,
                        "msg": f"Non-JSON response from FOFA (HTTP {resp.status}): {preview!r}",
                        "code": 1001,
                    }
                if not isinstance(data, dict):
                    return {
                        "error": True,
                        "msg": f"Unexpected JSON shape from FOFA: type={type(data).__name__}",
                        "code": 1001,
                    }
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
    # Reserve the estimated F-point cost up-front (budget mode only).
    reserved_cost = (page - 1) * size if page > 1 else 0
    ok, err = _check_fpoints(page, allow_fpoints, size)
    if not ok:
        return err  # type: ignore[return-value]

    qbase64 = base64.b64encode(query.encode()).decode()
    params = urllib.parse.urlencode({
        "key": key, "qbase64": qbase64,
        "fields": fields, "page": page, "size": size,
        "full": str(full).lower(),
    })
    resp = _request(f"{BASE_URL}/search/all?{params}")
    # If the request failed, FOFA never charged anything — refund the reservation
    # so a flaky network / API error doesn't deplete the session budget.
    if resp.get("error") and reserved_cost > 0:
        _refund_fpoints(reserved_cost)
    return resp


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
