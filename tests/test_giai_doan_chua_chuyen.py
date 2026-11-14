"""TẠM (PR 1–3 bỏ vnstock): giai đoạn còn gọi vnstock bị BỎ QUA khi máy không
cài vnstock (CI), thay vì gọi lỗi liên tục rồi nghỉ 180s theo cầu chì — mỗi
lần trickle phí ~20 phút Actions mà vẫn báo xanh (review PR 1, 12/11/2026)."""
import build_warehouse as bw
from src import ingest_market


def test_bo_qua_giai_doan_chua_chuyen_khi_khong_co_vnstock(monkeypatch):
    monkeypatch.setattr(ingest_market, "VNSTOCK_CO_SAN", False)
    for phase in ingest_market.GIAI_DOAN_CAN_VNSTOCK:
        assert bw._want(None, phase) is False, phase
        assert bw._want({phase}, phase) is False, phase


def test_giai_doan_da_chuyen_van_chay(monkeypatch):
    monkeypatch.setattr(ingest_market, "VNSTOCK_CO_SAN", False)
    for phase in ("prices", "index", "fx", "events"):
        assert phase not in ingest_market.GIAI_DOAN_CAN_VNSTOCK
        assert bw._want(None, phase) is True


def test_co_vnstock_thi_chay_nhu_cu(monkeypatch):
    monkeypatch.setattr(ingest_market, "VNSTOCK_CO_SAN", True)
    for phase in ingest_market.GIAI_DOAN_CAN_VNSTOCK:
        assert bw._want(None, phase) is True
    assert bw._want({"prices"}, "statements") is False
