"""Screener kết hợp value + momentum. Mỗi mã được chấm điểm theo số tiêu
chí đạt được; chỉ mã đạt CẢ hai nhóm mới vào danh sách cuối."""
from . import ingest, signals


def _check_value(ratios, cfg):
    hits, reasons = 0, []
    pe, pb, roe = ratios.get("pe"), ratios.get("pb"), ratios.get("roe")
    if pe is not None and pe <= cfg["pe_max"]:
        hits += 1; reasons.append(f"P/E {pe:.1f}≤{cfg['pe_max']}")
    if pb is not None and pb <= cfg["pb_max"]:
        hits += 1; reasons.append(f"P/B {pb:.1f}≤{cfg['pb_max']}")
    if roe is not None and roe >= cfg["roe_min"]:
        hits += 1; reasons.append(f"ROE {roe*100:.0f}%≥{cfg['roe_min']*100:.0f}%")
    return hits, reasons


def _check_momentum(sig, cfg):
    hits, reasons = 0, []
    close, ma50, rsi_v, r1m = sig.get("close"), sig.get("ma50"), sig.get("rsi"), sig.get("return_1m")
    if cfg.get("above_ma50") and close and ma50 and close > ma50:
        hits += 1; reasons.append("giá>MA50")
    if rsi_v is not None and cfg["rsi_min"] <= rsi_v <= cfg["rsi_max"]:
        hits += 1; reasons.append(f"RSI {rsi_v}")
    if r1m is not None and r1m >= cfg["return_1m_min"] * 100:
        hits += 1; reasons.append(f"+{r1m:.1f}%/1m")
    return hits, reasons


def run(cfg, source, run_date, exclude=()):
    """cfg = nội dung screener.yml đã load. Trả list dict đã xếp hạng."""
    uni_cfg = cfg["universe"]
    symbols = [s for s in ingest.fetch_universe(uni_cfg["group"], source) if s not in exclude]
    results = []
    for sym in symbols:
        df = ingest.fetch_history(sym, source, days=90)
        if df.empty:
            continue
        sig = signals.analyze(df)
        if sig.get("avg_volume", 0) and sig["avg_volume"] < uni_cfg["min_avg_volume"]:
            continue
        ratios = ingest.fetch_ratios(sym, source)

        v_hits, v_reasons = _check_value(ratios, cfg["value"])
        m_hits, m_reasons = _check_momentum(sig, cfg["momentum"])

        # Điều kiện vào danh sách: đạt >=2 tiêu chí value VÀ >=2 momentum.
        if v_hits >= 2 and m_hits >= 2:
            results.append({
                "run_date": run_date, "symbol": sym,
                "score": float(v_hits + m_hits),
                "reason": " | ".join(v_reasons + m_reasons),
            })
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[: cfg.get("top_n", 8)]
