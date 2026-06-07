"""Tính tín hiệu kỹ thuật từ lịch sử giá. Logic thuần, không AI -> số liệu
chính xác, dùng làm input cho phần AI diễn giải."""
import pandas as pd


def rsi(close: pd.Series, period: int = 14) -> float:
    if len(close) < period + 1:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, pd.NA)
    out = 100 - 100 / (1 + rs)
    val = out.iloc[-1]
    return round(float(val), 1) if pd.notna(val) else None


def _last(series):
    return float(series.iloc[-1]) if len(series) else None


def analyze(df: pd.DataFrame) -> dict:
    """Nhận OHLCV (cột: close, volume...) -> dict các chỉ số."""
    if df.empty or "close" not in df.columns:
        return {}
    close = df["close"].astype(float)
    vol = df["volume"].astype(float) if "volume" in df.columns else pd.Series(dtype=float)

    ma20 = close.rolling(20).mean()
    ma50 = close.rolling(50).mean()
    last_close = _last(close)
    prev_close = float(close.iloc[-2]) if len(close) > 1 else last_close

    res = {
        "close": last_close,
        "change_pct": round((last_close / prev_close - 1) * 100, 2) if prev_close else None,
        "ma20": round(_last(ma20), 1) if pd.notna(ma20.iloc[-1]) else None,
        "ma50": round(_last(ma50), 1) if pd.notna(ma50.iloc[-1]) else None,
        "rsi": rsi(close),
        "return_1m": round((last_close / float(close.iloc[-21]) - 1) * 100, 2) if len(close) > 21 else None,
    }
    if len(vol) >= 20:
        avg20 = vol.iloc[-21:-1].mean()
        res["vol_ratio"] = round(float(vol.iloc[-1]) / avg20, 2) if avg20 else None
        res["avg_volume"] = int(avg20)
    return res


def portfolio_row(symbol, holding, sig, ratios, run_date):
    """Gộp tín hiệu + lãi/lỗ so với giá vốn thành 1 dòng cho danh mục."""
    close = sig.get("close")
    pnl = None
    if close and holding.get("avg_price"):
        pnl = round((close / holding["avg_price"] - 1) * 100, 2)
    return {
        "run_date": run_date, "symbol": symbol, "close": close,
        "change_pct": sig.get("change_pct"), "pnl_pct": pnl,
        "rsi": sig.get("rsi"), "ma20": sig.get("ma20"), "ma50": sig.get("ma50"),
        "vol_ratio": sig.get("vol_ratio"),
        "pe": ratios.get("pe"), "pb": ratios.get("pb"),
    }
