"""Vietcap (VCI): danh sách mã, phân ngành ICB, bảng giá, lịch sử giá.

Tên cột giữ đúng như ingest_market đã đọc từ vnstock 4.0.9 (snake_case của
trường JSON), để phần chuẩn hoá phía sau không đổi.
"""
from __future__ import annotations

import re

import pandas as pd

from .http import SourceError, iq_data, get_json, post_json

TRADING = "https://trading.vietcap.com.vn/api"

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def snake(name: str) -> str:
    """camelCase → snake_case: refPrice → ref_price, accumulatedValueG1 → accumulated_value_g1."""
    return _CAMEL.sub("_", name).lower()


def all_symbols() -> pd.DataFrame:
    """Mọi mã cổ phiếu (type STOCK, gồm cả mã đã huỷ niêm yết): [symbol, organ_name].

    KHÔNG trả cột sàn — refresh_universe sẽ bật bộ lọc sàn vốn đang tắt
    (xem comment config/warehouse.yml)."""
    data = get_json(f"{TRADING}/price/symbols/getAll")
    if not isinstance(data, list):
        raise SourceError(f"getAll: phản hồi không phải danh sách ({type(data).__name__})")
    rows = [{"symbol": d.get("symbol"), "organ_name": d.get("organName")}
            for d in data if d.get("type") == "STOCK"]
    return pd.DataFrame(rows, columns=["symbol", "organ_name"])


def industries_icb() -> pd.DataFrame:
    """Bảng ICB 4 cấp: [icb_code, icb_name, en_icb_name, level], sắp theo mã."""
    data = iq_data("/v1/sectors/icb-codes") or []
    df = pd.DataFrame({
        "icb_code": [d.get("name") for d in data],
        "icb_name": [d.get("viSector") for d in data],
        "en_icb_name": [d.get("enSector") for d in data],
        "level": [d.get("icbLevel") for d in data],
    })
    return df.sort_values("icb_code", kind="stable").reset_index(drop=True)


_BOARD_GROUPS = {"listingInfo": "listing", "matchPrice": "match", "bidAsk": "bid_ask"}


def price_board(symbols: list[str]) -> pd.DataFrame:
    """Bảng giá nhiều mã. Cột đã làm phẳng `<nhóm>.<trường>`: listing.symbol,
    listing.trading_date, listing.ref_price, match.match_price, match.highest…
    Giá theo ĐỒNG; match.accumulated_value theo TRIỆU đồng (như nguồn)."""
    data = post_json(f"{TRADING}/price/symbols/getList", {"symbols": list(symbols)})
    if not isinstance(data, list):
        raise SourceError(f"getList: phản hồi không phải danh sách ({type(data).__name__})")
    if symbols and not data:
        # Rỗng cho một lô có mã = nguồn trục trặc, không phải "không có giá":
        # ném lỗi để lô được thử lại và vào failed_symbols (sự cố 05/10/2026).
        raise SourceError(f"getList: nguồn trả danh sách rỗng cho {len(symbols)} mã")
    rows = []
    for item in data:
        row = {}
        for key, group in _BOARD_GROUPS.items():
            for field, value in (item.get(key) or {}).items():
                if not isinstance(value, (dict, list)):
                    row[f"{group}.{snake(field)}"] = value
        rows.append(row)
    return pd.DataFrame(rows)


_VN_TZ = "Asia/Ho_Chi_Minh"
_OHLC_COLS = ["time", "open", "high", "low", "close", "volume"]
# Tên chỉ số phía nguồn khác tên dùng trong warehouse (đã đối chiếu yêu cầu
# vnstock gửi đi ngày 12/11/2026 với HNXINDEX).
_INDEX_ALIAS = {"HNXINDEX": "HNXIndex", "UPCOMINDEX": "HNXUpcomIndex"}


def ohlc_history(symbol: str, start: str, end: str) -> pd.DataFrame:
    """Nến ngày một mã hoặc chỉ số: [time, open, high, low, close, volume].

    Giá theo đơn vị CỦA NGUỒN: cổ phiếu là ĐỒNG (giá điều chỉnh có phần lẻ),
    chỉ số là điểm. Không chia 1000, không làm tròn, không cắt bớt lịch sử
    (vnstock gói cộng đồng cắt còn ~8 năm và làm tròn tới bậc 10 đồng).

    API nhận `to` (0 giờ giờ VN của ngày sau `end`) và `countBack` (số phiên
    đếm lùi) chứ không nhận ngày bắt đầu: countBack = số ngày làm việc trong
    [start, end+1] + 1. Ngày lễ không có phiên nên kết quả có thể bắt đầu sớm
    hơn `start` vài phiên — giữ nguyên như hành vi cũ."""
    end_next = pd.Timestamp(end) + pd.Timedelta(days=1)
    to = int(end_next.tz_localize(_VN_TZ).timestamp())
    count_back = len(pd.bdate_range(start=pd.Timestamp(start), end=end_next)) + 1
    data = post_json(f"{TRADING}/chart/OHLCChart/gap-chart",
                     {"timeFrame": "ONE_DAY", "symbols": [_INDEX_ALIAS.get(symbol.upper(), symbol)],
                      "to": to,
                      "countBack": count_back})
    if not isinstance(data, list):
        raise SourceError(f"gap-chart {symbol}: phản hồi không phải danh sách")
    if not data or not data[0].get("t"):
        return pd.DataFrame(columns=_OHLC_COLS)
    d = data[0]
    lengths = {len(d.get(k) or []) for k in ("t", "o", "h", "l", "c", "v")}
    if len(lengths) != 1:
        raise SourceError(f"gap-chart {symbol}: các mảng o/h/l/c/v/t lệch độ dài {lengths}")
    time_ = (pd.to_datetime(pd.Series(d["t"]).astype("int64"), unit="s", utc=True)
             .dt.tz_convert(_VN_TZ).dt.tz_localize(None).dt.normalize())
    return pd.DataFrame({
        "time": time_,
        "open": pd.Series(d["o"], dtype="float64"),
        "high": pd.Series(d["h"], dtype="float64"),
        "low": pd.Series(d["l"], dtype="float64"),
        "close": pd.Series(d["c"], dtype="float64"),
        "volume": pd.Series(d["v"], dtype="int64"),
    })
