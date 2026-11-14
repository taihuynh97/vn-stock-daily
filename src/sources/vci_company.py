"""Vietcap (iq.vietcap.com.vn): sự kiện, tin, hồ sơ công ty, cổ đông, ban lãnh
đạo, chỉ số tài chính tóm tắt.

Tên cột = snake_case của trường JSON, như ingest_market đã đọc từ vnstock 4.0.9.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from .http import SourceError, iq_data
from .vci import snake

# Cửa sổ ngày gửi cho /events và /news: 3650 ngày tới hôm nay (đúng yêu cầu
# vnstock gửi lúc chụp 12/11/2026: fromDate=20161114). Nguồn vẫn chỉ trả 50
# mục GẦN NHẤT mỗi mã (page=0, size=50).
WINDOW_DAYS = 3650
PAGE_SIZE = 50
EVENT_CODES = "DIV,ISS,DDIND,DDINS,DDRP,AGME,AGMR,EGME,AIS,MA,MOVE,NLIS,OTHE,RETU,SUSP"
# Trường ngày giờ cắt còn YYYY-MM-DD (vnstock làm vậy; ingest_market tự phân tích lại).
_EVENT_DATE_FIELDS = {"public_date", "issue_date", "record_date", "exright_date",
                      "listing_date", "start_date", "end_date", "payout_date"}
_EVENT_DROP = {"organ_code", "organ_name_en", "organ_name_vi"}


def _today() -> date:
    return date.today()


def _window() -> dict:
    today = _today()
    return {"fromDate": (today - timedelta(days=WINDOW_DAYS)).strftime("%Y%m%d"),
            "toDate": today.strftime("%Y%m%d")}


def _content(data, what: str) -> list[dict]:
    if data is None:
        return []
    if isinstance(data, dict) and isinstance(data.get("content"), list):
        return data["content"]
    raise SourceError(f"{what}: phản hồi thiếu danh sách content ({type(data).__name__})")


def _frame(items: list[dict], drop=frozenset()) -> pd.DataFrame:
    rows = [{snake(k): v for k, v in it.items() if snake(k) not in drop} for it in items]
    return pd.DataFrame(rows)


def events(symbol: str) -> pd.DataFrame:
    """50 sự kiện gần nhất: id, event_code, event_name_vi, event_title_vi,
    category, action_type_vi, exercise_ratio, value_per_share, các cột ngày…"""
    data = iq_data("/v1/events", {"ticker": symbol, **_window(), "eventCode": EVENT_CODES,
                                  "page": 0, "size": PAGE_SIZE})
    df = _frame(_content(data, f"events {symbol}"), drop=_EVENT_DROP)
    for col in _EVENT_DATE_FIELDS & set(df.columns):
        df[col] = df[col].where(df[col].isna(), df[col].astype(str).str[:10])
    return df
