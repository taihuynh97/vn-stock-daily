"""HTTP client dùng chung cho nguồn Vietcap (src/sources/http.py)."""
import json

import pytest
import requests

from src.sources import http
from tests.vci_fixtures import FakeResponse


@pytest.fixture
def calls(monkeypatch):
    """Vá _send bằng hàng đợi phản hồi; ghi lại các lời gọi và các lần ngủ."""
    state = {"queue": [], "sent": [], "slept": []}

    def _send(method, url, *, params=None, json=None, headers=None):
        state["sent"].append((method, url, params, json))
        item = state["queue"].pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(http, "_send", _send)
    monkeypatch.setattr(http.time, "sleep", lambda s: state["slept"].append(s))
    return state


def ok(payload, status=200):
    return FakeResponse(status, json.dumps(payload))


def test_iq_data_boc_vo(calls):
    calls["queue"] = [ok({"status": 200, "code": 0, "msg": "Successful", "data": [1]})]
    assert http.iq_data("/v1/x", {"ticker": "FPT"}) == [1]
    method, url, params, _ = calls["sent"][0]
    assert method == "GET"
    assert url == "https://iq.vietcap.com.vn/api/iq-insight-service/v1/x"
    assert params == {"ticker": "FPT"}


def test_iq_data_vo_loi_nem_source_error(calls):
    calls["queue"] = [ok({"status": 400, "code": 1, "msg": "x", "data": None})]
    with pytest.raises(http.SourceError):
        http.iq_data("/v1/x")


def test_json_hong_nem_source_error(calls):
    calls["queue"] = [FakeResponse(200, "<html>bảo trì</html>")]
    with pytest.raises(http.SourceError):
        http.get_json("https://trading.vietcap.com.vn/api/x")


def test_thu_lai_khi_5xx_roi_thanh_cong(calls):
    calls["queue"] = [FakeResponse(503, ""), FakeResponse(503, ""), ok([7])]
    assert http.post_json("https://trading.vietcap.com.vn/api/x", {"a": 1}) == [7]
    assert len(calls["sent"]) == 3
    assert calls["slept"] == [5, 15]
    assert calls["sent"][0][3] == {"a": 1}


def test_thu_lai_khi_loi_ket_noi(calls):
    calls["queue"] = [requests.ConnectionError("rớt"), ok([1])]
    assert http.get_json("https://trading.vietcap.com.vn/api/x") == [1]
    assert calls["slept"] == [5]


def test_het_luot_thu_lai_nem_source_error(calls):
    calls["queue"] = [FakeResponse(429, "")] * 3
    with pytest.raises(http.SourceError):
        http.get_json("https://trading.vietcap.com.vn/api/x")
    assert len(calls["sent"]) == 3


def test_khong_thu_lai_khi_4xx(calls):
    calls["queue"] = [FakeResponse(404, "")]
    with pytest.raises(http.SourceError):
        http.get_json("https://trading.vietcap.com.vn/api/x")
    assert len(calls["sent"]) == 1
    assert calls["slept"] == []


def test_header_bat_buoc():
    h = http.session().headers
    assert h["Referer"] == "https://trading.vietcap.com.vn/"
    assert h["Origin"] == "https://trading.vietcap.com.vn/"
    assert "Mozilla/5.0" in h["User-Agent"]
    assert h["Accept"] == "application/json, text/plain, */*"
