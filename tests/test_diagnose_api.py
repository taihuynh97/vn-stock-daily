"""Phần tính thống kê của scripts/diagnose_api.py — không gọi mạng."""
from scripts import diagnose_api as d


def _r(ep, s, ok=True, err=""):
    return {"endpoint": ep, "seconds": s, "ok": ok, "error_type": err}


def test_summarize_tính_p50_p95_và_đếm_chậm():
    recs = [_r("events", s) for s in [1, 2, 3, 4, 40]] + [_r("events", 31, False, "RetryError")]
    s = d.summarize(recs)[0]
    assert s["endpoint"] == "events" and s["n"] == 6
    assert s["p50_s"] == 3.5
    assert s["max_s"] == 40
    assert s["n_over_5s"] == 2 and s["n_over_30s"] == 2
    assert s["n_error"] == 1 and s["errors"] == {"RetryError": 1}
    assert s["total_s"] == 81


def test_summarize_giữ_thứ_tự_endpoint_như_job_thật():
    recs = [_r("cash_flow", 1), _r("ratio_summary", 1), _r("events", 1)]
    assert [s["endpoint"] for s in d.summarize(recs)] == ["ratio_summary", "events", "cash_flow"]


def test_markdown_báo_dừng_sớm_và_lỗi():
    recs = [_r("events", 1), _r("events", 30, False, "rỗng")]
    meta = {"where": "github", "vnstock": "4.0.9", "python": "3.12", "n_symbols": 1,
            "min_interval": "1.05", "started_utc": "2026-10-04 10:00", "elapsed_min": 1.0,
            "stopped_early": True}
    md = d.to_markdown(d.summarize(recs), meta)
    assert "DỪNG SỚM" in md
    assert "events: rỗng ×1" in md
    assert "| events | 2 | 1 |" in md
