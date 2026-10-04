"""Chẩn đoán độ trễ API vnstock (VCI) — chạy được trên máy cá nhân và trên GitHub.

Câu hỏi cần trả lời (xem docs/Q-ket-qua-va-no-ky-thuat.md + thảo luận 04/10/2026):
job warehouse-weekly không chạy xong trong 350 phút. Trên máy cá nhân ở VN, một lần
gọi BCTC mất 0,4–1,4 giây; trên GitHub (máy chủ Mỹ) bước BCTC đo được ~5 giây/lần,
và bước sự kiện DN không xong từ 01/10 (sau khi nâng vnstock 4.0.9). Nguyên nhân là
VỊ TRÍ máy chạy hay CODE/nguồn? Chạy script này ở cả hai nơi rồi so.

Script CHỈ ĐỌC: gọi đúng các endpoint mà job tuần dùng cho một mẫu mã cố định,
đo thời gian của RIÊNG lệnh gọi (không tính thời gian chờ giãn cách
VNSTOCK_MIN_INTERVAL), ghi lỗi theo loại. Không kết nối MotherDuck, không ghi gì.

    python -u -m scripts.diagnose_api                     # mẫu mặc định 30 mã
    python -u -m scripts.diagnose_api --n 10 --out diag.json
"""
import argparse
import json
import os
import platform
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

# Mẫu cố định, trộn HOSE/HNX/UPCoM, thanh khoản cao/thấp, ngân hàng/phi tài chính
# — để kết quả hai nơi chạy so sánh được với nhau.
DEFAULT_SYMBOLS = [
    "FPT", "HPG", "VCB", "MBB", "PNJ", "REE", "VNM", "SSI", "GAS", "MWG",
    "PHR", "TRC", "DGC", "IDC", "LHG", "PVS", "SHS", "CEO", "NTP", "IDV",
    "BSR", "VEA", "ACV", "MCH", "QNS", "AAH", "ABR", "BCF", "MLS", "VNR",
]

ENDPOINTS = ["ratio_summary", "events", "income_statement", "balance_sheet",
             "cash_flow", "history", "price_board"]


def summarize(records: list[dict]) -> list[dict]:
    """Gộp các lần gọi theo endpoint: số lần, lỗi, p50/p95/max, số lần chậm.

    `records`: [{endpoint, seconds, ok, error_type}] — `seconds` là thời gian
    của riêng lệnh gọi. p50/p95 tính trên MỌI lần gọi (kể cả lỗi): một lần gọi
    lỗi sau 30 giây chờ timeout vẫn là 30 giây job phải trả.
    """
    out = []
    for ep in sorted({r["endpoint"] for r in records}, key=lambda e: (
            ENDPOINTS.index(e) if e in ENDPOINTS else 99, e)):
        rs = [r for r in records if r["endpoint"] == ep]
        secs = sorted(r["seconds"] for r in rs)
        n = len(secs)
        p95_idx = min(n - 1, max(0, int(round(0.95 * (n - 1)))))
        errors: dict[str, int] = {}
        for r in rs:
            if not r["ok"]:
                errors[r["error_type"]] = errors.get(r["error_type"], 0) + 1
        out.append({
            "endpoint": ep,
            "n": n,
            "n_error": sum(errors.values()),
            "p50_s": round(statistics.median(secs), 2),
            "p95_s": round(secs[p95_idx], 2),
            "max_s": round(secs[-1], 2),
            "n_over_5s": sum(1 for s in secs if s > 5),
            "n_over_30s": sum(1 for s in secs if s > 30),
            "total_s": round(sum(secs), 1),
            "errors": errors,
        })
    return out


def to_markdown(summary: list[dict], meta: dict) -> str:
    lines = [
        f"### Độ trễ API vnstock — {meta['where']}",
        "",
        f"vnstock {meta['vnstock']} · Python {meta['python']} · "
        f"{meta['n_symbols']} mã · giãn cách {meta['min_interval']} giây · "
        f"bắt đầu {meta['started_utc']} UTC · {meta['elapsed_min']} phút"
        + (" · **DỪNG SỚM do hết ngân sách thời gian**" if meta["stopped_early"] else ""),
        "",
        "| Endpoint | Lần gọi | Lỗi | p50 (s) | p95 (s) | Max (s) | >5s | >30s | Tổng (s) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for s in summary:
        lines.append(
            f"| {s['endpoint']} | {s['n']} | {s['n_error']} | {s['p50_s']} | {s['p95_s']} "
            f"| {s['max_s']} | {s['n_over_5s']} | {s['n_over_30s']} | {s['total_s']} |")
    errs = [(s["endpoint"], k, v) for s in summary for k, v in s["errors"].items()]
    if errs:
        lines += ["", "Lỗi theo loại: " + "; ".join(f"{e}: {k} ×{v}" for e, k, v in errs)]
    return "\n".join(lines)


def _call(records, endpoint, fn, throttle):
    throttle()
    t0 = time.monotonic()
    ok, err = True, ""
    try:
        res = fn()
        if res is None or len(res) == 0:
            ok, err = False, "rỗng"
    except Exception as e:  # ghi loại lỗi, không dừng script
        ok, err = False, type(e).__name__
    dt = time.monotonic() - t0
    records.append({"endpoint": endpoint, "seconds": dt, "ok": ok, "error_type": err})
    print(f"  {endpoint:<17} {dt:6.2f}s {'ok' if ok else 'LỖI ' + err}", flush=True)


def main():
    load_dotenv()
    ap = argparse.ArgumentParser(description="Đo độ trễ API vnstock (chỉ đọc)")
    ap.add_argument("--n", type=int, default=len(DEFAULT_SYMBOLS), help="Số mã trong mẫu")
    ap.add_argument("--max-minutes", type=float, default=40,
                    help="Ngân sách thời gian; hết thì dừng và báo kết quả dở dang")
    ap.add_argument("--out", help="Ghi kết quả JSON ra file")
    ap.add_argument("--where", default=os.getenv("DIAG_WHERE") or platform.node())
    args = ap.parse_args()

    key = os.getenv("VNSTOCK_API_KEY")
    if key:
        from vnstock import vnai
        vnai.setup_api_key(key)

    from importlib.metadata import version
    from vnstock.api.company import Company
    from vnstock.api.financial import Finance
    from vnstock.api.quote import Quote
    from vnstock.api.trading import Trading
    from src import ingest  # dùng chung _throttle với job thật

    symbols = DEFAULT_SYMBOLS[: args.n]
    started = datetime.now(timezone.utc)
    deadline = time.monotonic() + args.max_minutes * 60
    end = started.date().isoformat()
    start = (started.date() - timedelta(days=14)).isoformat()
    records: list[dict] = []
    stopped_early = False

    _call(records, "price_board", lambda: Trading(source="VCI").price_board(symbols_list=symbols),
          ingest._throttle)
    for i, sym in enumerate(symbols, 1):
        if time.monotonic() > deadline:
            stopped_early = True
            print(f"Hết ngân sách {args.max_minutes} phút sau {i - 1} mã — dừng.", flush=True)
            break
        print(f"[{i}/{len(symbols)}] {sym}", flush=True)
        _call(records, "ratio_summary",
              lambda: Company(symbol=sym, source="VCI").ratio_summary(), ingest._throttle)
        _call(records, "events", lambda: Company(symbol=sym, source="VCI").events(), ingest._throttle)
        for st in ("income_statement", "balance_sheet", "cash_flow"):
            _call(records, st,
                  lambda st=st: getattr(Finance(symbol=sym, source="VCI", period="quarter"), st)(),
                  ingest._throttle)
        _call(records, "history",
              lambda: Quote(symbol=sym, source="VCI").history(start=start, end=end, interval="1D"),
              ingest._throttle)

    meta = {
        "where": args.where,
        "vnstock": version("vnstock"),
        "python": platform.python_version(),
        "n_symbols": len({r for r in symbols}),
        "min_interval": os.getenv("VNSTOCK_MIN_INTERVAL", "3.1"),
        "started_utc": started.strftime("%Y-%m-%d %H:%M"),
        "elapsed_min": round((datetime.now(timezone.utc) - started).total_seconds() / 60, 1),
        "stopped_early": stopped_early,
    }
    summary = summarize(records)
    md = to_markdown(summary, meta)
    print("\n" + md, flush=True)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(md + "\n")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"meta": meta, "summary": summary, "records": records}, f,
                      ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
