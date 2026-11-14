"""Dựng fixture test cho src/sources từ đáp án mẫu chụp vnstock 4.0.9 (12/11/2026).

Chạy MỘT LẦN, trên máy có thư mục đáp án mẫu (ngoài git) và code ingest_market
CŨ (còn gọi lớp vnstock):

    python -m scripts.build_vci_fixtures data/vnstock_golden_2026-11-12

Với mỗi hàm `fetch_*` của ingest_market, script thay các lớp vnstock mà
ingest_market đã import (Listing, Trading, Quote, Company, Finance,
vcb_exchange_rate) bằng lớp giả trả frame mẫu, chạy hàm đó, rồi ghi đầu ra
làm ĐÁP ÁN (`tests/fixtures/vci/expected/<tên>.json`). Phản hồi HTTP thô của
nguồn lúc chụp được nén vào `tests/fixtures/vci/http/<nhãn>.json.gz` để test
lớp mới chạy offline trên đúng dữ liệu đó.

Hợp đồng: lớp mới (src/sources) + ingest_market mới, chạy trên phản hồi HTTP
thô, phải cho ra đúng đáp án — tức là dữ liệu nạp vào warehouse không đổi.
Không cần mạng, không gọi vnstock thật (chỉ cần import được để vá).
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import ingest, ingest_market  # noqa: E402
from tests.vci_fixtures import assert_same, dump_expected, read_expected  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "vci"
SYMS = ["FPT", "HPG", "VCB", "SSI", "BVH", "PVS", "MCH"]
STMT_SYMS = ["FPT", "VCB", "SSI", "BVH"]
INDICES = ["VNINDEX", "VN30", "HNXINDEX"]
SNAPSHOT = "2026-11-12"
STATEMENTS = ["income_statement", "balance_sheet", "cash_flow"]

# Khoảng ngày đúng như lúc chụp (scratchpad capture_golden.py).
HIST_RANGE = ("2026-10-01", "2026-11-11")
LONG_RANGE = ("2012-01-01", "2026-11-11")


def main(golden: Path) -> None:
    frames = golden / "frames"

    def frame(label: str) -> pd.DataFrame:
        return pd.read_pickle(frames / f"{label}.pkl").copy()

    class FakeListing:
        def __init__(self, source=None):
            pass

        def all_symbols(self):
            return frame("listing_all_symbols")

        def industries_icb(self):
            return frame("listing_industries_icb")

    class FakeTrading:
        def __init__(self, source=None):
            pass

        def price_board(self, symbols_list):
            return frame("price_board")

    class FakeQuote:
        def __init__(self, symbol, source=None):
            self.symbol = symbol

        def history(self, start, end, interval="1D"):
            suffix = "_long" if start == LONG_RANGE[0] else ""
            return frame(f"history_{self.symbol}{suffix}")

    class FakeCompany:
        def __init__(self, symbol, source=None):
            self.symbol = symbol

        def __getattr__(self, method):
            return lambda *a, **k: frame(f"company_{method}_{self.symbol}")

    class FakeFinance:
        def __init__(self, symbol, source=None, period="quarter"):
            self.symbol, self.period = symbol, period

        def __getattr__(self, st):
            return lambda *a, **k: frame(f"finance_{st}_{self.period}_{self.symbol}")

    ingest_market.Listing = FakeListing
    ingest_market.Trading = FakeTrading
    ingest_market.Quote = FakeQuote
    ingest_market.Company = FakeCompany
    ingest_market.Finance = FakeFinance
    ingest_market.vcb_exchange_rate = lambda date: frame(f"fx_vcb_{date}")
    ingest._throttle = lambda: None

    exp_dir = OUT / "expected"
    exp_dir.mkdir(parents=True, exist_ok=True)

    def save(name: str, df: pd.DataFrame) -> None:
        path = exp_dir / f"{name}.json.gz"
        dump_expected(df, path)
        assert_same(df, read_expected(path))  # đọc lại phải ra đúng bảng gốc
        print(f"expected/{name}.json.gz  {df.shape}")

    im = ingest_market
    save("universe", im.refresh_universe(["HOSE", "HNX"]))
    save("industries_icb", im.fetch_industries_icb())
    save("eod_prices", im.fetch_eod_prices(SYMS, run_date=SNAPSHOT))
    save("fx_2026-11-11", im.fetch_exchange_rate("2026-11-11"))
    for ix in INDICES:
        save(f"index_{ix}", im.fetch_index_history(ix, *HIST_RANGE))
    save("history_FPT_long", im.fetch_history_one("FPT", *LONG_RANGE))
    for s in SYMS:
        save(f"history_{s}", im.fetch_history_one(s, *HIST_RANGE))
        save(f"events_{s}", im.fetch_corporate_events([s]))
        save(f"news_{s}", im.fetch_news([s]))
        save(f"company_{s}", im.fetch_company_info([s]))
        save(f"shareholders_{s}", im.fetch_shareholders([s], snapshot_date=SNAPSHOT))
        save(f"officers_{s}", im.fetch_officers([s], snapshot_date=SNAPSHOT))
        save(f"ratio_summary_{s}", im.fetch_financials([s]))
    for s in STMT_SYMS:
        for period in ["quarter", "year"]:
            for st in STATEMENTS:
                row, status = im._fetch_statement_one(s, st, "VCI", period)
                assert status == "ok", (s, st, period, status)
                save(f"stmt_{st}_{period}_{s}", row)

    write_http(golden / "http")


def _keep_label(label: str) -> bool:
    if label.startswith("finance_"):
        return label.rsplit("_", 1)[-1] in STMT_SYMS
    return True


def _trim_search_bar(body: str) -> str:
    """search-bar trả ~1,3 MB (mọi mã). Chỉ giữ dòng của mã trong mẫu."""
    doc = json.loads(body)
    data = doc.get("data")
    if isinstance(data, list):
        doc["data"] = [d for d in data if isinstance(d, dict)
                       and any(v in SYMS for v in d.values() if isinstance(v, str))]
    return json.dumps(doc, ensure_ascii=False)


def write_http(http_dir: Path) -> None:
    out = OUT / "http"
    out.mkdir(parents=True, exist_ok=True)
    for f in sorted(http_dir.glob("*.json")):
        label = f.stem
        if not _keep_label(label):
            continue
        reqs = []
        for r in json.loads(f.read_text()):
            if r["url"].rstrip("/").endswith("/priceboard"):
                continue  # trang HTML, không phải dữ liệu
            if "search-bar" in r["url"]:
                r = {**r, "body": _trim_search_bar(r["body"])}
            r.pop("headers", None)
            reqs.append(r)
        with gzip.open(out / f"{label}.json.gz", "wt", encoding="utf-8") as g:
            json.dump(reqs, g, ensure_ascii=False)
    total = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    print(f"tổng fixture: {total / 1e6:.2f} MB")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
