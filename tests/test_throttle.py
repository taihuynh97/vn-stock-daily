"""Bộ giãn cách gọi API dùng chung cho nhiều luồng (BCTC song song)."""
import threading
import time

from src import ingest


def test_nhiều_luồng_vẫn_giữ_khoảng_cách_tối_thiểu(monkeypatch):
    monkeypatch.setattr(ingest, "_MIN_CALL_INTERVAL", 0.05)
    monkeypatch.setattr(ingest, "_next_slot", 0.0)
    stamps, lock = [], threading.Lock()

    def worker():
        for _ in range(5):
            ingest._throttle()
            with lock:
                stamps.append(time.monotonic())

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stamps.sort()
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert len(stamps) == 20
    # Sai số lập lịch của hệ điều hành: cho phép hụt 10 ms.
    assert min(gaps) >= 0.04
    # Tổng thời gian xấp xỉ 19 khoảng — không chậm hơn tuần tự đáng kể.
    assert stamps[-1] - stamps[0] < 19 * 0.05 + 0.5


def test_một_luồng_lần_gọi_đầu_không_phải_chờ(monkeypatch):
    monkeypatch.setattr(ingest, "_MIN_CALL_INTERVAL", 0.5)
    monkeypatch.setattr(ingest, "_next_slot", 0.0)
    t0 = time.monotonic()
    ingest._throttle()
    assert time.monotonic() - t0 < 0.05
