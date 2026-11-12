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
    rows = []
    for item in data:
        row = {}
        for key, group in _BOARD_GROUPS.items():
            for field, value in (item.get(key) or {}).items():
                if not isinstance(value, (dict, list)):
                    row[f"{group}.{snake(field)}"] = value
        rows.append(row)
    return pd.DataFrame(rows)
