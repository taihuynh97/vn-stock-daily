"""Thời gian chờ mặc định của vnstock.send_request (04/10/2026).

Nguồn iq.vietcap.com.vn treo lần thử đầu đủ 30 giây khi bóp lưu lượng; vnstock
thử lại tới 9 lần nên một mã lỗi tốn ~5 phút. Hạ mặc định xuống 15 giây (lệnh
bình thường 0,1–7 giây) → mã lỗi tốn ~2,5 phút, mã "treo lần đầu" ~17 giây.
"""
import importlib
import inspect


def _default_timeout():
    from vnstock.core.utils import client
    return inspect.signature(client.send_request).parameters["timeout"].default


def test_mặc_định_15_giây_khi_nạp_ingest(monkeypatch):
    monkeypatch.delenv("VNSTOCK_REQUEST_TIMEOUT", raising=False)
    from src import ingest
    ingest.apply_vnstock_timeout()
    assert _default_timeout() == 15


def test_đổi_được_qua_biến_môi_trường(monkeypatch):
    from src import ingest
    monkeypatch.setenv("VNSTOCK_REQUEST_TIMEOUT", "20")
    ingest.apply_vnstock_timeout()
    assert _default_timeout() == 20
    monkeypatch.delenv("VNSTOCK_REQUEST_TIMEOUT")
    ingest.apply_vnstock_timeout()
    assert _default_timeout() == 15


def test_lệnh_gọi_sự_kiện_thật_dùng_mặc_định_này():
    """Company.events() gọi send_request KHÔNG truyền timeout — đổi mặc định là đủ."""
    src = inspect.getsource(importlib.import_module("vnstock.explorer.vci.company"))
    i = src.index("def _fetch_events(")
    call = src[src.index("send_request(", i): src.index(")", src.index("send_request(", i)) + 1]
    assert "timeout" not in call
