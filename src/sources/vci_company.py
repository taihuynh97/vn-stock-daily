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


def news(symbol: str) -> pd.DataFrame:
    """50 tin gần nhất: id, news_title, news_short_content, news_source_link,
    public_date (giữ nguyên giờ, ingest_market tự phân tích)…"""
    data = iq_data("/v1/news", {"ticker": symbol, **_window(), "languageId": 1,
                                "page": 0, "size": PAGE_SIZE})
    return _frame(_content(data, f"news {symbol}"))


# Trường hồ sơ cần đổi tên so với snake_case thuần (tên ingest_market đọc).
_OVERVIEW_RENAME = {"ticker": "symbol", "vi_organ_name": "organ_name",
                    "vi_organ_short_name": "organ_short_name"}


def overview(symbol: str) -> pd.DataFrame:
    """Hồ sơ một dòng: symbol, organ_name, organ_short_name, com_group_code,
    com_type_code, is_bank, icb_code_lv2/lv4, sector, market_cap, issue_share,
    tỷ lệ sở hữu, thanh khoản 1 tháng, giá cao/thấp 1 năm, listing_date…

    issue_share = issueShare (số cổ phiếu phát hành). vnstock gộp nhiều trường
    vào 4 cột trùng tên issue_share nên pipeline cũ luôn đọc ra NULL."""
    data = iq_data("/v1/company/details", {"ticker": symbol})
    if not data:
        return pd.DataFrame()
    if not isinstance(data, dict):
        raise SourceError(f"company/details {symbol}: phản hồi không phải object")
    row = {}
    for k, v in data.items():
        if isinstance(v, (dict, list)):
            continue
        col = snake(k)
        row[_OVERVIEW_RENAME.get(col, col)] = v
    row.setdefault("symbol", symbol)
    return pd.DataFrame([row])


def _owners(symbol: str) -> list[dict]:
    """/company/{symbol}/shareholder: cổ đông và người nội bộ chung một danh sách
    (người nội bộ có positionName)."""
    data = iq_data(f"/v1/company/{symbol}/shareholder")
    if data is None:
        return []
    if not isinstance(data, list):
        raise SourceError(f"shareholder {symbol}: phản hồi không phải danh sách")
    return data


def shareholders(symbol: str) -> pd.DataFrame:
    """[symbol, share_holder, quantity, share_own_percent, update_date]."""
    rows = [{"symbol": symbol, "share_holder": r.get("ownerName"), "quantity": r.get("quantity"),
             "share_own_percent": r.get("percentage"), "update_date": r.get("updateDate")}
            for r in _owners(symbol)]
    return pd.DataFrame(rows, columns=["symbol", "share_holder", "quantity",
                                       "share_own_percent", "update_date"])


def officers(symbol: str) -> pd.DataFrame:
    """Người nội bộ (cá nhân có chức vụ): [symbol, officer_name, officer_position,
    officer_own_percent, officer_own_quantity, update_date]."""
    rows = [{"symbol": symbol, "officer_name": r.get("ownerName"),
             "officer_position": r.get("positionName"), "officer_own_percent": r.get("percentage"),
             "officer_own_quantity": r.get("quantity"), "update_date": r.get("updateDate")}
            # Như vnstock cũ: cá nhân có chức vụ (khác null; chuỗi rỗng vẫn tính).
            # Tổ chức có chức vụ (đại diện vốn) không phải người nội bộ.
            for r in _owners(symbol)
            if r.get("positionName") is not None and r.get("ownerType", "INDIVIDUAL") == "INDIVIDUAL"]
    return pd.DataFrame(rows, columns=["symbol", "officer_name", "officer_position",
                                       "officer_own_percent", "officer_own_quantity",
                                       "update_date"])


def ratio_summary(symbol: str) -> pd.DataFrame:
    """Chỉ số tài chính theo kỳ (TTM theo quý + năm): symbol, year, quarter,
    ratio_type, pe, pb, roe, … (snake_case của trường nguồn)."""
    data = iq_data(f"/v1/company/{symbol}/statistics-financial")
    if data is None:
        return pd.DataFrame()
    if not isinstance(data, list):
        raise SourceError(f"statistics-financial {symbol}: phản hồi không phải danh sách")
    df = _frame(data)
    df.insert(0, "symbol", symbol)
    return df
