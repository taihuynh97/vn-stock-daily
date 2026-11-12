"""HTTP client dùng chung cho nguồn Vietcap.

Một `requests.Session` dùng lại (giữ kết nối). Thời gian chờ (10, 30) giây.
Thử lại TỐI ĐA 2 lần (nghỉ 5s rồi 15s) chỉ khi lỗi kết nối/timeout/HTTP 429/
5xx — vnstock cũ thử 9 lần × 30s nên một mã treo tốn ~5 phút (04/10/2026).
Mọi lỗi cuối cùng là `SourceError` để các vòng try/except của ingest_market
ghi nhận "error" như trước.
"""
from __future__ import annotations

import time
from typing import Any

import requests

IQ_BASE = "https://iq.vietcap.com.vn/api/iq-insight-service"
TIMEOUT = (10, 30)
RETRY_WAITS = (5, 15)
_RETRY_STATUS = {429, 500, 502, 503, 504}

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    "Content-Type": "application/json",
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"),
    "Referer": "https://trading.vietcap.com.vn/",
    "Origin": "https://trading.vietcap.com.vn/",
}


class SourceError(Exception):
    """Nguồn lỗi: mạng, HTTP không thành công, JSON hỏng, vỏ phản hồi báo lỗi."""


_session: requests.Session | None = None


def session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(HEADERS)
    return _session


def _send(method: str, url: str, *, params: dict | None = None,
          json: Any = None, headers: dict | None = None) -> requests.Response:
    """Điểm I/O mạng DUY NHẤT — test vá hàm này. `headers` đè header của
    session cho riêng yêu cầu này; giá trị None = bỏ header đó."""
    return session().request(method, url, params=params, json=json, headers=headers,
                             timeout=TIMEOUT)


def _request(method: str, url: str, *, params: dict | None = None, json: Any = None,
             headers: dict | None = None) -> Any:
    last = None
    for attempt in range(len(RETRY_WAITS) + 1):
        if attempt:
            time.sleep(RETRY_WAITS[attempt - 1])
        try:
            resp = _send(method, url, params=params, json=json, headers=headers)
        except (requests.ConnectionError, requests.Timeout) as e:
            last = f"{type(e).__name__}: {e}"
            continue
        if resp.status_code in _RETRY_STATUS:
            last = f"HTTP {resp.status_code}"
            continue
        if resp.status_code != 200:
            raise SourceError(f"{method} {url}: HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError as e:
            raise SourceError(f"{method} {url}: phản hồi không phải JSON ({resp.text[:80]!r})") from e
    raise SourceError(f"{method} {url}: hết lượt thử lại ({last})")


def get_json(url: str, params: dict | None = None, headers: dict | None = None) -> Any:
    return _request("GET", url, params=params, headers=headers)


def post_json(url: str, body: dict) -> Any:
    return _request("POST", url, json=body)


def iq_data(path: str, params: dict | None = None) -> Any:
    """GET iq.vietcap.com.vn, bóc vỏ {status, code, msg, data} → data."""
    url = IQ_BASE + path
    doc = get_json(url, params)
    if not isinstance(doc, dict) or doc.get("status") != 200 or doc.get("code") not in (0, None):
        msg = doc.get("msg") if isinstance(doc, dict) else str(doc)[:80]
        raise SourceError(f"GET {url}: nguồn báo lỗi ({msg})")
    return doc.get("data")
