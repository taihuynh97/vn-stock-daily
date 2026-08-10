"""Ingestion toàn thị trường (Phase 1): danh sách mã + giá EOD bulk.

Dùng:
  - Listing.all_symbols()          → refresh universe (dim_symbols)
  - Trading.price_board(symbols)   → giá EOD nhiều mã / 1 call (bulk, rẻ)

Mọi call đi qua ingest._throttle() để dùng chung ngân sách rate limit với job digest.
Vì cấu trúc cột của price_board tuỳ nguồn, phần chuẩn hoá cột được tách riêng và
in ra cột thật ở lần chạy đầu để dễ tinh chỉnh.
"""
import re
from datetime import date
import pandas as pd

from vnstock.api.listing import Listing
from vnstock.api.trading import Trading
from vnstock.api.quote import Quote
from vnstock.api.company import Company
from . import ingest, warehouse, dq  # tái dùng _throttle (chung ngân sách rate limit)

_TICKER = re.compile(r"^[A-Z]{3}$")          # cổ phiếu VN: đúng 3 chữ cái
_EXCH_NORM = {"HSX": "HOSE", "HOSE": "HOSE", "HNX": "HNX", "UPCOM": "UPCOM"}
_printed_cols = False


def is_trading_day(d: date) -> bool:
    """True nếu d là ngày giao dịch (T2-T6). Chưa tính lịch nghỉ lễ VN."""
    return d.weekday() < 5


def refresh_universe(exchanges, source: str = "VCI") -> pd.DataFrame:
    """Trả DataFrame [symbol, exchange, company_name] đã lọc theo sàn & chỉ cổ phiếu."""
    ingest._throttle()
    try:
        df = Listing(source=source).all_symbols()
    except Exception as e:
        print(f"[universe] {e}")
        return pd.DataFrame()
    if df is None or len(df) == 0:
        return pd.DataFrame()

    df.columns = [str(c).lower() for c in df.columns]
    sym_col = _find(df.columns, "symbol", "ticker", "code")
    exch_col = _find(df.columns, "exchange", "board", "comgroupcode", "group")
    name_col = _find(df.columns, "organ", "company", "name")
    if sym_col is None:
        print(f"[universe] không tìm thấy cột symbol trong: {list(df.columns)}")
        return pd.DataFrame()

    out = pd.DataFrame({"symbol": df[sym_col].astype(str).str.upper().str.strip()})
    out["exchange"] = (df[exch_col].astype(str).str.upper().map(lambda x: _EXCH_NORM.get(x, x))
                       if exch_col else None)
    out["company_name"] = df[name_col].astype(str) if name_col else None

    out = out[out["symbol"].apply(lambda s: bool(_TICKER.match(s)))]   # chỉ cổ phiếu
    if exch_col:
        wanted = {_EXCH_NORM.get(e.upper(), e.upper()) for e in exchanges}
        out = out[out["exchange"].isin(wanted)]
    return out.drop_duplicates("symbol").reset_index(drop=True)


def fetch_industries_icb(source: str = "VCI") -> pd.DataFrame:
    """Bảng phân ngành ICB 4 cấp (bảng tĩnh, ~177 dòng, tên ngành tiếng Việt)."""
    ingest._throttle()
    try:
        df = Listing(source=source).industries_icb()
    except Exception as e:
        print(f"[industries_icb] {e}")
        return pd.DataFrame()
    if df is None or len(df) == 0:
        return pd.DataFrame()

    df.columns = [str(c).lower() for c in df.columns]
    dq.assert_columns(df, ["icb_code", "icb_name", "level"], "Listing.industries_icb")

    out = pd.DataFrame({
        "icb_code":    df["icb_code"].astype(str).str.strip(),
        "icb_name":    df["icb_name"].astype(str).str.strip(),
        "en_icb_name": (df["en_icb_name"].astype(str).str.strip()
                        if "en_icb_name" in df.columns else None),
        "level":       pd.to_numeric(df["level"], errors="coerce").astype("Int64"),
    })
    return out.drop_duplicates("icb_code").reset_index(drop=True)


def fetch_eod_prices(symbols, source: str = "VCI", batch_size: int = 50) -> pd.DataFrame:
    """Giá EOD cho danh sách mã qua bulk price_board. Trả DataFrame raw_price_daily."""
    global _printed_cols
    trade_date = date.today().isoformat()
    frames = []
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        ingest._throttle()
        try:
            df = Trading(source=source).price_board(symbols_list=batch)
        except Exception as e:
            print(f"[price_board] batch {i//batch_size}: {e}")
            continue
        if df is None or len(df) == 0:
            continue
        df.columns = ['.'.join(map(str, c)).lower() if isinstance(c, tuple) else str(c).lower()
                      for c in df.columns]
        if not _printed_cols:
            print(f"[price_board] cột thật: {list(df.columns)}")
            _printed_cols = True
        frames.append(df)

    if not frames:
        return pd.DataFrame()
    raw = pd.concat(frames, ignore_index=True)
    return _normalize_board(raw, trade_date)


def _normalize_board(df, trade_date) -> pd.DataFrame:
    """Map cột price_board → schema raw_price_daily. close+volume là bắt buộc;
    open/high/low để None (sẽ lấp đầy ở Phase 1.5 backfill qua Quote.history)."""
    cols = list(df.columns)
    sym = _find(cols, "symbol", "ticker", "code")
    close = _find(cols, "match_price", "matchprice", "last_price", "close", "price")
    vol = _find(cols, "accumulated_volume", "total_volume", "totalvol", "volume", "nmtotaltradedqty")
    openc = _find(cols, "open_price", "open")
    high = _find(cols, "high_price", "highest")
    low = _find(cols, "low_price", "lowest")
    val = _find(cols, "accumulated_value", "total_value", "value")

    if sym is None or close is None:
        print(f"[normalize] thiếu cột symbol/close. Cột có: {cols}")
        return pd.DataFrame()

    out = pd.DataFrame({
        "symbol": df[sym].astype(str).str.upper().str.strip(),
        "trade_date": trade_date,
        "open": _col(df, openc),
        "high": _col(df, high),
        "low": _col(df, low),
        "close": pd.to_numeric(df[close], errors="coerce"),
        "volume": pd.to_numeric(df[vol], errors="coerce") if vol else None,
        "value": _col(df, val),
    })
    return out.dropna(subset=["close"]).drop_duplicates("symbol").reset_index(drop=True)


def _find(cols, *keys):
    for c in cols:
        if any(k in c for k in keys):
            return c
    return None


def _col(df, name):
    return pd.to_numeric(df[name], errors="coerce") if name else None


_printed_hist_cols = False
_printed_fin_cols = False
_printed_info_cols = False


def fetch_history_one(symbol: str, start: str, end: str, source: str = "VCI") -> pd.DataFrame:
    """Lịch sử OHLCV một mã qua Quote.history. Trả DataFrame schema raw_price_daily."""
    global _printed_hist_cols
    ingest._throttle()
    try:
        df = Quote(symbol=symbol, source=source).history(start=start, end=end, interval="1D")
    except Exception as e:
        print(f"[history] {symbol}: {e}")
        return pd.DataFrame()

    if df is None or len(df) == 0:
        return pd.DataFrame()

    df.columns = [str(c).lower() for c in df.columns]
    if not _printed_hist_cols:
        print(f"[history] cột thật ({symbol}): {list(df.columns)}")
        _printed_hist_cols = True

    cols = list(df.columns)
    date_col  = _find(cols, "trading_date", "time", "date")
    close_col = _find(cols, "close")
    open_col  = _find(cols, "open")
    high_col  = _find(cols, "high")
    low_col   = _find(cols, "low")
    vol_col   = _find(cols, "volume")
    val_col   = _find(cols, "value")

    if date_col is None or close_col is None:
        print(f"[history] {symbol}: thiếu cột date/close. Cột có: {cols}")
        return pd.DataFrame()

    out = pd.DataFrame({
        "symbol":     symbol.upper().strip(),
        "trade_date": pd.to_datetime(df[date_col]).dt.strftime("%Y-%m-%d"),
        "open":       _col(df, open_col),
        "high":       _col(df, high_col),
        "low":        _col(df, low_col),
        "close":      pd.to_numeric(df[close_col], errors="coerce"),
        "volume":     pd.to_numeric(df[vol_col], errors="coerce") if vol_col else None,
        "value":      _col(df, val_col),
    })
    # vnstock (VCI) trả OHLC của Quote.history theo đơn vị nghìn đồng,
    # trong khi Trading.price_board (daily ingestion) trả VND. Nhân lại 1000
    # để raw_price_daily đồng nhất đơn vị giữa backfill và daily.
    for col in ("open", "high", "low", "close"):
        if pd.api.types.is_numeric_dtype(out[col]):
            out[col] = out[col] * 1000
    return out.dropna(subset=["close"]).drop_duplicates(["symbol", "trade_date"]).reset_index(drop=True)


def fetch_index_history(index_code: str, start: str, end: str,
                        source: str = "VCI") -> pd.DataFrame:
    """Lịch sử chỉ số (VNINDEX/VN30/HNXINDEX).

    KHÁC fetch_history_one: chỉ số KHÔNG nhân ×1000. fetch_history_one nhân
    OHLC với 1000 vì Quote.history của VCI trả giá CỔ PHIẾU theo đơn vị nghìn
    đồng. Chỉ số thì không — xác minh 2026-08-07:
    Quote.history('VNINDEX').close = 1768.06, đã đúng đơn vị điểm chỉ số
    (nhân 1000 sẽ ra 1.768.060, sai hoàn toàn). Vì vậy hàm này viết riêng,
    không tái dùng/sửa fetch_history_one.
    """
    ingest._throttle()
    try:
        df = Quote(symbol=index_code, source=source).history(
            start=start, end=end, interval="1D"
        )
    except Exception as e:
        print(f"[index] {index_code}: {e}")
        return pd.DataFrame()
    if df is None or len(df) == 0:
        return pd.DataFrame()

    df.columns = [str(c).lower() for c in df.columns]
    dq.assert_columns(df, ["close"], f"Quote.history({index_code})")
    date_col = _find(list(df.columns), "trading_date", "time", "date")
    if date_col is None:
        raise dq.SchemaError(
            f"[Quote.history({index_code})] không tìm thấy cột ngày. "
            f"Cột thật: {list(df.columns)}"
        )

    out = pd.DataFrame({
        "index_code": index_code.upper().strip(),
        "trade_date": pd.to_datetime(df[date_col]).dt.strftime("%Y-%m-%d"),
        "open":   _col(df, _find(list(df.columns), "open")),
        "high":   _col(df, _find(list(df.columns), "high")),
        "low":    _col(df, _find(list(df.columns), "low")),
        "close":  pd.to_numeric(df["close"], errors="coerce"),
        "volume": _col(df, _find(list(df.columns), "volume")),
    })
    out = out.dropna(subset=["close"])
    out, rejected = dq.filter_range(out, "close", 1, 100_000)
    if rejected:
        print(f"[index] {index_code}: loại {rejected} dòng close ngoài [1, 100.000]")
    return out.drop_duplicates(["index_code", "trade_date"]).reset_index(drop=True)


def fetch_financials(symbols: list[str], source: str = "VCI") -> pd.DataFrame:
    """Tỷ số tài chính theo quý (TTM) + cả năm qua Company.ratio_summary().

    Company.ratio_summary() trả mỗi dòng = 1 quý, quarter 1-4 = TTM kết thúc
    tại quý đó (ratio_type=RATIO_TTM), quarter=5 = tổng cả năm (RATIO_YEAR).
    """
    global _printed_fin_cols
    frames = []
    for symbol in symbols:
        ingest._throttle()
        try:
            df = Company(symbol=symbol, source=source).ratio_summary()
        except Exception as e:
            print(f"[financials] {symbol}: {e}")
            continue
        if df is None or len(df) == 0:
            continue
        df.columns = [str(c).lower() for c in df.columns]
        if not _printed_fin_cols:
            print(f"[financials] cột thật ({symbol}): {list(df.columns)}")
            _printed_fin_cols = True
        row = _normalize_financials(df, symbol)
        if row is not None and not row.empty:
            frames.append(row)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _normalize_financials(df, symbol) -> pd.DataFrame:
    dq.assert_columns(df, ["year", "quarter"], f"ratio_summary({symbol})")

    out = pd.DataFrame({
        "symbol":  symbol.upper().strip(),
        "year":    pd.to_numeric(df["year"], errors="coerce"),
        "quarter": pd.to_numeric(df["quarter"], errors="coerce"),
    })
    out["period_type"] = out["quarter"].apply(lambda q: "year" if q == 5 else "quarter")
    if "ratio_type" in df.columns:
        out["ratio_type"] = df["ratio_type"].astype(str).values
    else:
        out["ratio_type"] = out["quarter"].apply(
            lambda q: "RATIO_YEAR" if q == 5 else "RATIO_TTM"
        )
    for col in warehouse.RATIO_NUM_COLS:
        out[col] = pd.to_numeric(df[col], errors="coerce") if col in df.columns else None

    out = out.dropna(subset=["year", "quarter"]).reset_index(drop=True)
    return out[warehouse.RATIO_ALL_COLS]


def fetch_company_info(symbols: list[str], source: str = "VCI") -> pd.DataFrame:
    global _printed_info_cols
    frames = []
    for symbol in symbols:
        ingest._throttle()
        try:
            df = Company(symbol=symbol, source=source).overview()
        except Exception as e:
            print(f"[company_info] {symbol}: {e}")
            continue
        if df is None or len(df) == 0:
            continue
        df.columns = [str(c).lower() for c in df.columns]
        if not _printed_info_cols:
            print(f"[company_info] cột thật ({symbol}): {list(df.columns)}")
            _printed_info_cols = True
        row = _normalize_company(df, symbol)
        if row is not None and not row.empty:
            frames.append(row)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


_COMPANY_REQUIRED = ["symbol", "com_group_code", "icb_code_lv2"]

# com_group_code của Company.overview() trả TÊN CHỈ SỐ ("VNINDEX", "HNXIndex",
# "UpcomIndex"), không phải mã sàn thô — xác minh lại bằng API thật ngày
# 2026-08-10 với HPG/VCB/SSI (đều "VNINDEX"), SHS/PVS/MBS ("HNXIndex"), VGT
# ("UpcomIndex"), BSR ("VNINDEX", khớp việc BSR chuyển từ UPCOM sang HOSE
# 2024). Brief giả định giá trị là "HOSE" trực tiếp — không đúng với API
# thật. Chuẩn hoá về HOSE/HNX/UPCOM để khớp config/warehouse.yml (lọc theo
# đúng các giá trị này), nếu không dim_symbols.exchange sẽ chứa "VNINDEX"
# thay vì NULL — sai dữ liệu chứ không sửa được bug lọc sàn.
_COM_GROUP_TO_EXCHANGE = {
    "VNINDEX": "HOSE",
    "HNXINDEX": "HNX",
    "UPCOMINDEX": "UPCOM",
}


_warned_unknown_exchange = False


def _map_exchange(raw) -> str | None:
    """Map com_group_code -> exchange canonical (HOSE/HNX/UPCOM).

    Giá trị lạ (không có trong _COM_GROUP_TO_EXCHANGE) trả None thay vì trả
    nguyên chuỗi thô: chuỗi lạ ghi thẳng vào raw_company_info.exchange rồi
    lan qua dim_symbols.exchange sẽ giả dạng dữ liệu hợp lệ trong khi thực ra
    không xác định được sàn — hiệu ứng lọc downstream giống hệt None (bị loại
    khỏi exchanges: [HOSE, HNX]), nhưng None nói thật "không biết", chuỗi lạ
    thì không. In cảnh báo một lần (theo pattern _printed_info_cols cùng
    file) để không spam khi chạy toàn bộ ~1.598 mã.
    """
    global _warned_unknown_exchange
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    v = str(raw).strip().upper()
    if not v:
        return None
    mapped = _COM_GROUP_TO_EXCHANGE.get(v)
    if mapped is not None:
        return mapped
    if not _warned_unknown_exchange:
        print(f"[company_info] com_group_code lạ, không map được sàn: {v!r}")
        _warned_unknown_exchange = True
    return None


def _to_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return False
    return str(v).strip().lower() in {"1", "true", "t", "yes", "y"}


def _to_date_str(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return pd.to_datetime(v).date().isoformat()
    except Exception:
        return None


def _normalize_company(df, symbol) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    dq.assert_columns(df, _COMPANY_REQUIRED, f"Company.overview({symbol})")
    row = df.iloc[0]

    def num(col):
        return pd.to_numeric(pd.Series([row.get(col)]), errors="coerce").iloc[0] \
            if col in df.columns else None

    def text(col):
        v = row.get(col) if col in df.columns else None
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        return str(v).strip()

    return pd.DataFrame([{
        "symbol":                     symbol.upper().strip(),
        "company_name":               text("organ_name"),
        "short_name":                 text("organ_short_name"),
        "exchange":                   _map_exchange(row.get("com_group_code")),
        "com_type_code":              text("com_type_code"),
        "is_bank":                    _to_bool(row.get("is_bank")),
        "icb_code_lv2":               text("icb_code_lv2"),
        "icb_code_lv4":               text("icb_code_lv4"),
        "sector":                     text("sector"),
        "market_cap":                 num("market_cap"),
        "issue_share":                num("issue_share"),
        "free_float_percentage":      num("free_float_percentage"),
        "foreigner_percentage":       num("foreigner_percentage"),
        "maximum_foreign_percentage": num("maximum_foreign_percentage"),
        "state_percentage":           num("state_percentage"),
        "avg_match_value_1m":         num("average_match_value1_month"),
        "avg_match_volume_1m":        num("average_match_volume1_month"),
        "highest_price_1y":           num("highest_price1_year"),
        "lowest_price_1y":            num("lowest_price1_year"),
        "listed_date":                _to_date_str(row.get("listing_date")),
    }])[warehouse.COMPANY_COLS]
