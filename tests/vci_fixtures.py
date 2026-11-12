"""Helper fixture cho test src/sources (dựng bởi scripts/build_vci_fixtures.py).

- `load_expected(name)`: đáp án = đầu ra hàm `fetch_*` của ingest_market CŨ
  (còn vnstock 4.0.9) trên dữ liệu chụp ngày 12/11/2026.
- `fake_http(monkeypatch, *labels)`: vá `src.sources.http._send` để phục vụ
  phản hồi HTTP thô đã ghi lúc chụp. Yêu cầu không có trong fixture → lỗi
  ghi rõ URL (bắt được việc lớp mới gọi sai endpoint/tham số/body).
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import pandas as pd

FIXTURES = Path(__file__).parent / "fixtures" / "vci"


# ---------- đáp án ----------

def dump_expected(df: pd.DataFrame, path: Path) -> None:
    df = df.reset_index(drop=True)
    payload = {
        "attrs": {k: v for k, v in df.attrs.items()
                  if isinstance(v, (str, int, float, list, type(None)))},
        "dtypes": {c: str(t) for c, t in df.dtypes.items()},
        "table": json.loads(df.to_json(orient="split", date_format="iso",
                                       date_unit="ns", index=False)),
    }
    with gzip.open(path, "wt", encoding="utf-8") as g:
        json.dump(payload, g, ensure_ascii=False)


def read_expected(path: Path) -> pd.DataFrame:
    with gzip.open(path, "rt", encoding="utf-8") as g:
        payload = json.load(g)
    t = payload["table"]
    df = pd.DataFrame(t["data"], columns=t["columns"])
    for col, dtype in payload["dtypes"].items():
        if dtype.startswith("datetime64"):
            df[col] = pd.to_datetime(df[col]).astype(dtype)
        elif dtype == "object":
            df[col] = df[col].astype(object).where(df[col].notna(), None)
        else:
            df[col] = df[col].astype(dtype)
    df.attrs.update(payload["attrs"])
    return df


def load_expected(name: str) -> pd.DataFrame:
    return read_expected(FIXTURES / "expected" / f"{name}.json.gz")


def assert_same(actual: pd.DataFrame, expected: pd.DataFrame) -> None:
    """So nguyên bảng: tên cột, thứ tự cột/dòng, dtype, giá trị."""
    actual = actual.reset_index(drop=True)
    pd.testing.assert_frame_equal(actual, expected, check_dtype=True)
    for k, v in expected.attrs.items():
        assert actual.attrs.get(k) == v, f"attrs[{k!r}]: {actual.attrs.get(k)!r} != {v!r}"


# ---------- HTTP giả ----------

def _body(rec_json, rec_data):
    body = rec_json if rec_json is not None else rec_data
    if isinstance(body, str):
        try:
            return json.loads(body)
        except ValueError:
            return body
    return body


def _key(method: str, url: str, params, body):
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    query.update({k: str(v) for k, v in (params or {}).items()})
    return (method.upper(), f"{parts.scheme}://{parts.netloc}{parts.path}".rstrip("/"),
            tuple(sorted(query.items())), json.dumps(body, sort_keys=True))


class FakeResponse:
    def __init__(self, status: int, text: str):
        self.status_code = status
        self.text = text

    def json(self):
        return json.loads(self.text)


def load_http(label: str) -> list[dict]:
    with gzip.open(FIXTURES / "http" / f"{label}.json.gz", "rt", encoding="utf-8") as g:
        return json.load(g)


def block_network(monkeypatch) -> None:
    """Mọi requests thật (kể cả qua thư viện bên thứ ba) → lỗi. fake_http
    thay `_send` nên không đi qua đây."""
    import requests

    def _blocked(self, method, url, *a, **k):
        raise AssertionError(f"test không được gọi mạng: {method} {url}")

    monkeypatch.setattr(requests.Session, "request", _blocked)


def fake_http(monkeypatch, *labels: str) -> list[tuple]:
    """Vá src.sources.http._send. Trả danh sách khoá các yêu cầu đã gửi."""
    from src.sources import http

    table = {}
    for label in labels:
        for r in load_http(label):
            k = _key(r["method"], r["url"], r["params"], _body(r["json"], r["data"]))
            table.setdefault(k, r)
    sent: list[tuple] = []

    def _send(method, url, *, params=None, json=None):
        k = _key(method, url, params, json)
        sent.append(k)
        if k not in table:
            known = "\n  ".join(map(str, table))
            raise AssertionError(f"yêu cầu không có trong fixture:\n  {k}\nđã ghi:\n  {known}")
        r = table[k]
        return FakeResponse(r["status"], r["body"])

    monkeypatch.setattr(http, "_send", _send)
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    return sent
