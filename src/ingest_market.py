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
from vnstock.api.financial import Finance
from vnstock.api.company import Company
from . import ingest  # tái dùng _throttle (chung ngân sách rate limit)

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


def fetch_financials(symbols: list[str], source: str = "VCI") -> pd.DataFrame:
    global _printed_fin_cols
    frames = []
    for symbol in symbols:
        ingest._throttle()
        try:
            df = Finance(symbol=symbol, source=source, period="year").ratio()
        except Exception as e:
            print(f"[financials] {symbol}: {e}")
            continue
        if df is None or len(df) == 0:
            continue
        df.columns = [
            '.'.join(map(str, c)).lower() if isinstance(c, tuple) else str(c).lower()
            for c in df.columns
        ]
        if not _printed_fin_cols:
            print(f"[financials] cột thật ({symbol}): {list(df.columns)}")
            _printed_fin_cols = True
        row = _normalize_financials(df, symbol)
        if row is not None and not row.empty:
            frames.append(row)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _normalize_financials(df, symbol) -> pd.DataFrame:
    cols = list(df.columns)
    period_col = _find(cols, "yearreport", "year", "period", "quarter", "reportdate")
    pe_col = _find(cols, "pe", "p/e", "price_to_earn")
    pb_col = _find(cols, "pb", "p/b", "price_to_book")
    roe_col = _find(cols, "roe")
    roa_col = _find(cols, "roa")
    eps_col = _find(cols, "eps")

    if period_col is None:
        print(f"[financials] {symbol}: không tìm thấy cột period. Cột có: {cols}")
        return pd.DataFrame()

    out = pd.DataFrame({
        "symbol":      symbol.upper().strip(),
        "period":      df[period_col].astype(str),
        "period_type": "year",
        "pe":          pd.to_numeric(df[pe_col],  errors="coerce") if pe_col  else None,
        "pb":          pd.to_numeric(df[pb_col],  errors="coerce") if pb_col  else None,
        "roe":         pd.to_numeric(df[roe_col], errors="coerce") if roe_col else None,
        "roa":         pd.to_numeric(df[roa_col], errors="coerce") if roa_col else None,
        "eps":         pd.to_numeric(df[eps_col], errors="coerce") if eps_col else None,
    })
    return out.dropna(subset=["period"]).reset_index(drop=True)


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


def _normalize_company(df, symbol) -> pd.DataFrame:
    cols = list(df.columns)
    name_col     = _find(cols, "organ_name", "company_name", "short_name", "company")
    exch_col     = _find(cols, "exchange", "comgroupcode", "board")
    industry_col = _find(cols, "industry_icb", "industry", "icb_name", "ngành")
    sector_col   = _find(cols, "sector", "sector_name")
    listed_col   = _find(cols, "listing_date", "listed_date", "ipo")

    if df.empty:
        return pd.DataFrame()
    row = df.iloc[0]

    listed_val = None
    if listed_col and pd.notna(row[listed_col]):
        try:
            listed_val = pd.to_datetime(row[listed_col]).date().isoformat()
        except Exception:
            listed_val = None

    return pd.DataFrame([{
        "symbol":       symbol.upper().strip(),
        "company_name": str(row[name_col]).strip()     if name_col     else None,
        "exchange":     str(row[exch_col]).upper()     if exch_col     else None,
        "industry_icb": str(row[industry_col]).strip() if industry_col else None,
        "sector":       str(row[sector_col]).strip()   if sector_col   else None,
        "listed_date":  listed_val,
    }])
