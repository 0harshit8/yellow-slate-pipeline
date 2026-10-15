"""One HTTP door to Yellow Slate's pipeline API. Both the CMS and blog clients go through here.

Their tech team handed over one base URL and one bearer key covering all five endpoints
(/health, /schools/search, /schools, /media, /blogs), so base URL and key live in one place
rather than one pair per client.

Documented behaviour this encodes (handover Oct 10 2026, their API update Oct 11 2026):
  401  missing or wrong key                       UNAUTHORIZED
  403  IP not on the allowlist, once PIPELINE_ALLOWED_IPS is set on their side
  404  unknown city, or no school of that name    UNKNOWN_CITY / SCHOOL_NOT_FOUND
  413  body over 6 MB
  429  over 300 requests a minute per IP, honour Retry-After    RATE_LIMITED
  503  key not configured on their side, or a database is down

Since Oct 11 2026 every error carries a machine-readable "code". Branch on that, never on
the message text, which they reword. The two 404s mean opposite things and used to be one
error here: UNKNOWN_CITY is a bad input that stops the batch, SCHOOL_NOT_FOUND just means
this school is not in their CMS yet, which is the normal case for a school we are about to
create. An unknown AREA is no longer an error at all - they create missing areas now.
"""

import time

import requests

import config

TIMEOUT = 60
RETRIES = 3           # on 429 and 5xx only, never on a 4xx we caused
BACKOFF = 2.0         # seconds, doubled per attempt, only when there is no Retry-After


class YSApiError(RuntimeError):
    """One error type for every transport failure. The CMS and blog clients re-raise as their own.

    "code" is their machine-readable error code where they sent one (UNKNOWN_CITY,
    SCHOOL_NOT_FOUND, AMBIGUOUS_MATCH, INVALID_INPUT, UNAUTHORIZED, RATE_LIMITED...),
    otherwise "". Callers branch on it instead of matching on the message.
    """

    def __init__(self, message, status=None, body="", code=""):
        super().__init__(message)
        self.status = status
        self.body = body
        self.code = code


class UnknownPlace(YSApiError):
    """Their CMS does not know this city. Never retried, and never treated as 'no match'.

    Named for the days when a bad area raised it too. Since Oct 11 2026 only a city can be
    unknown: a missing area is created on their side, so it is no longer an error.
    """


class NotInCms(YSApiError):
    """SCHOOL_NOT_FOUND: no school of this name, so it has to be created. Not a failure."""


def base_url():
    url = (config.YS_API_BASE or "").strip().rstrip("/")
    if not url:
        raise YSApiError("YS_API_BASE is not set. Put it in .env.")
    return url


def _key():
    key = (config.YS_API_KEY or "").strip()
    if not key:
        raise YSApiError("YS_API_KEY is not set. Put it in .env (gitignored), never in a tracked file.")
    return key


def _retry_after(response, attempt):
    header = response.headers.get("Retry-After", "")
    try:
        return max(1.0, float(header))
    except ValueError:
        return BACKOFF * (2 ** attempt)


def call(method, path, json_body=None, files=None, data=None, params=None):
    """Returns the parsed body. Raises YSApiError on anything that is not a 2xx.

    A 429 or 5xx is retried with backoff. A 4xx is the caller's fault, so it is raised at once.
    """
    url = f"{base_url()}/{path.lstrip('/')}"
    headers = {"Authorization": f"Bearer {_key()}"}
    if json_body is not None:
        headers["Content-Type"] = "application/json"

    last = None
    for attempt in range(RETRIES):
        try:
            response = requests.request(method, url, headers=headers, json=json_body,
                                        files=files, data=data, params=params, timeout=TIMEOUT)
        except requests.RequestException as exc:
            last = YSApiError(f"Could not reach {method} {path}: {exc}")
            time.sleep(BACKOFF * (2 ** attempt))
            continue

        if response.status_code == 429 or response.status_code >= 500:
            last = YSApiError(_message(response, method, path), response.status_code,
                              response.text[:400], _code(response))
            if attempt < RETRIES - 1:
                time.sleep(_retry_after(response, attempt))
                continue

        if response.ok:
            try:
                return response.json()
            except ValueError:
                raise YSApiError(f"Non-JSON reply from {method} {path}: {response.text[:200]}",
                                 response.status_code, response.text[:400])

        code = _code(response)
        args = (_message(response, method, path), response.status_code, response.text[:400], code)
        # Their code decides the type, not the status: both of these are 404 and only one of
        # them is a problem. Fall back to the status for an error sent before this update.
        if code == "SCHOOL_NOT_FOUND":
            raise NotInCms(*args)
        if code == "UNKNOWN_CITY" or (not code and response.status_code == 404):
            raise UnknownPlace(*args)
        raise YSApiError(*args)

    raise last


def _code(response):
    """Their machine-readable error code, or "" when there is none."""
    try:
        body = response.json()
    except ValueError:
        return ""
    return str(body.get("code", "") or "") if isinstance(body, dict) else ""


def _message(response, method, path):
    """Their errors come back as {"success": false, "message": "..."}. Use that text when it is there."""
    detail = ""
    try:
        body = response.json()
        if isinstance(body, dict):
            detail = str(body.get("message", "") or "")
    except ValueError:
        detail = response.text[:200]

    code = response.status_code
    hint = {
        401: "key missing or wrong",
        403: "this IP is not on their allowlist (PIPELINE_ALLOWED_IPS)",
        413: "body over 6 MB",
        429: "over 300 requests a minute",
        503: "their key is unconfigured or a database is down",
    }.get(code, "")
    label = f"{code} {_code(response)}".strip()
    parts = [f"Yellow Slate API {label} on {method} {path}"]
    if detail:
        parts.append(detail)
    if hint:
        parts.append(f"({hint})")
    return ": ".join(parts[:2]) + (f" {parts[2]}" if len(parts) > 2 else "")


def unwrap(body):
    """Their replies wrap the payload: {"success": true, "data": {...}}. Returns the data."""
    if isinstance(body, dict) and "data" in body:
        return body["data"]
    return body


def health():
    """The raw /health reply. Raises on 503, so a batch can stop before it starts."""
    return call("GET", "health")
