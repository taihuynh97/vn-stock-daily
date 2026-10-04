"""Bộ ngắt mạch cho các vòng lặp theo mã (ratios, events, company info, sở hữu).

Lý do (04/10/2026): từ máy chủ GitHub, iq.vietcap.com.vn hết thời gian chờ liên
tục ở bước sự kiện — mỗi mã tốn ~5 phút (9 lần thử x 30 giây), 51 phút mới đi
được ~120/1.603 mã. Không có ngắt mạch, giai đoạn này chạy hàng chục giờ và
GitHub cắt job trước khi dbt kịp chạy.
"""
import time
from unittest.mock import patch

from src import ingest


def test_lỗi_liên_tiếp_thì_nghỉ_rồi_dừng():
    br = ingest.SourceBreaker("events", pause_after=2, pause_seconds=5, max_pauses=1)
    sleeps = []
    with patch("src.ingest.time.sleep", side_effect=sleeps.append):
        seen = 0
        for _ in range(10):
            if not br.before():
                break
            seen += 1
            br.record(False)
    assert sleeps == [5]
    assert br.stopped and br.reason == "nguon_treo"
    assert seen == 4 and br.n_errors == 4 and br.n_done == 4


def test_thành_công_đặt_lại_bộ_đếm():
    br = ingest.SourceBreaker("events", pause_after=2, pause_seconds=5, max_pauses=0)
    for ok in [False, True, False, True, False]:
        assert br.before()
        br.record(ok)
    assert not br.stopped and br.n_errors == 3


def test_hạn_chót_dừng_trước_mã_kế_tiếp():
    br = ingest.SourceBreaker("ratios", deadline=time.monotonic() - 1)
    assert br.before() is False
    assert br.stopped and br.reason == "het_ngan_sach" and br.n_done == 0


def test_mặc_định_đọc_từ_biến_môi_trường(monkeypatch):
    monkeypatch.setenv("SOURCE_PAUSE_AFTER", "7")
    monkeypatch.setenv("SOURCE_PAUSE_SECONDS", "11")
    monkeypatch.setenv("SOURCE_MAX_PAUSES", "4")
    br = ingest.SourceBreaker("x")
    assert (br.pause_after, br.pause_seconds, br.max_pauses) == (7, 11.0, 4)


def test_tóm_tắt_cho_nhật_ký():
    br = ingest.SourceBreaker("events", pause_after=1, pause_seconds=0, max_pauses=0)
    with patch("src.ingest.time.sleep"):
        br.before(); br.record(False)
    assert "dung som: nguon_treo" in br.notes()


def test_fetch_corporate_events_dừng_khi_nguồn_chặn():
    """Mô phỏng đúng ca 04/10: mọi lệnh gọi sự kiện đều hết thời gian chờ."""
    from src import ingest_market

    calls = []

    def blocked(symbol, source):
        calls.append(symbol)
        raise ConnectionError("Read timed out. (read timeout=30)")

    br = ingest.SourceBreaker("events", pause_after=3, pause_seconds=0, max_pauses=2)
    with patch("src.ingest_market.Company", side_effect=blocked), \
         patch("src.ingest_market.ingest._throttle"), \
         patch("src.ingest.time.sleep"):
        out = ingest_market.fetch_corporate_events([f"S{i:04d}" for i in range(1603)], breaker=br)
    assert len(calls) == 9                      # 3 lỗi → nghỉ, 3 → nghỉ, 3 → dừng
    assert br.stopped and br.reason == "nguon_treo"
    assert out.empty


def test_phase_status_partial_khi_dừng_sớm():
    import build_warehouse as bw
    br = ingest.SourceBreaker("x", deadline=time.monotonic() - 1)
    br.before()
    assert bw._phase_status(br, 100) == "partial"
    assert bw._phase_status(ingest.SourceBreaker("y"), 0) == "empty"
