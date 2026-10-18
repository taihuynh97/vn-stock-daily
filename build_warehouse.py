"""Job thu thập warehouse — Phase 1: dim_symbols + giá EOD toàn thị trường.

Chạy độc lập với main.py (job bản tin). Chạy sau giờ đóng cửa mỗi ngày.

    python build_warehouse.py

Biến môi trường:
  WAREHOUSE_DB     (tuỳ chọn) đường dẫn DuckDB. Mặc định data/warehouse.duckdb.
                   Đặt 'md:vn_market' để ghi lên MotherDuck cloud.
  motherduck_token (nếu dùng MotherDuck)
  VNSTOCK_API_KEY  (khuyến nghị) nâng rate limit lên 60 req/phút.
"""
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import pandas as pd
import yaml
from dotenv import load_dotenv

from src import ingest, ingest_market, warehouse

load_dotenv()
ROOT = Path(__file__).resolve().parent


# --- Fix trần 360 phút của GitHub Actions (final review B2) ---
# Số mã mỗi lô fetch+ghi BCTC. Bản đầu gom TOÀN BỘ ~1.600 mã rồi mới gọi
# upsert_financial_statements MỘT lần ở cuối — nghĩa là một job bị GitHub
# giết giữa chừng (trần CỨNG 360 phút; job monthly đo thật ở Task 5 mất 767
# phút) ghi được 0 dòng BCTC: được ăn cả, ngã về không. Ghi theo lô thì các
# lô ĐÃ xong đã nằm thật trong raw_financial_statement nhờ INSERT OR
# REPLACE, lần chạy tháng sau chỉ tiếp tục phần còn thiếu (idempotent,
# không trùng lặp, không mất dữ liệu).
STATEMENT_CHUNK_SIZE = 100

# Bỏ qua fetch period="year" cho mã đã có dòng year được ghi trong ngần này
# ngày. BCTC năm hiếm khi đổi (chỉ đổi khi có báo cáo kiểm toán mới — spec
# B2 §1.4), nên fetch lại MỖI THÁNG cho ~1.600 mã là lãng phí thời gian
# lớn trong khi job đang vượt trần CI. Lần chạy ĐẦU TIÊN (bảng chưa có dòng
# year nào) vẫn fetch toàn bộ như thường; cơ chế này chỉ có tác dụng từ lần
# chạy tháng THỨ HAI trở đi.
STATEMENT_YEAR_FRESH_DAYS = 300


def _log(msg: str) -> None:
    """In kèm mốc giờ UTC — để đọc được mỗi giai đoạn mất bao lâu từ log CI
    (trước 04/10/2026 log không có giờ và bị giữ trong bộ đệm, không đo được)."""
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}Z] {msg}", flush=True)


PHASES = ['prices', 'index', 'fx', 'news', 'ratios', 'events', 'company', 'company_missing',
          'statements', 'statements_year']


class _Skip(Exception):
    """Bỏ qua một giai đoạn bọc try/except do --only không chọn nó."""


def _parse_only(raw):
    """--only "events,statements" → {"events", "statements"}; None → mọi giai đoạn."""
    if not raw:
        return None
    chosen = {x.strip() for x in raw.split(",") if x.strip()}
    unknown = chosen - set(PHASES)
    if unknown:
        raise SystemExit(f"--only: giai đoạn lạ {sorted(unknown)}. Có: {', '.join(PHASES)}")
    return chosen


def _want(only, phase) -> bool:
    return only is None or phase in only


def _budget_deadline() -> float | None:
    """Hạn chót (time.monotonic) từ INGEST_BUDGET_MINUTES; không đặt → None.

    Job tuần/tháng bị GitHub cắt ở 350 phút mọi tuần từ 05/09/2026 nên các
    bước dbt phía sau chưa từng chạy. Có ngân sách, bước nạp tự dừng sớm và
    thoát bình thường; workflow chạy dbt với `if: !cancelled()`."""
    raw = os.getenv("INGEST_BUDGET_MINUTES")
    return time.monotonic() + float(raw) * 60 if raw else None


def _over_budget(deadline) -> bool:
    return deadline is not None and time.monotonic() > deadline


def _skip_for_budget(con, mode, table, deadline, run_date) -> bool:
    """True (và ghi etl_load_log 'partial') nếu đã hết ngân sách trước giai đoạn này."""
    if not _over_budget(deadline):
        return False
    _log(f"{table}: BỎ QUA — hết ngân sách INGEST_BUDGET_MINUTES")
    warehouse.log_load(con, f"warehouse_{mode}", table, 0, "partial",
                       watermark=run_date, notes="het_ngan_sach: bo qua giai doan")
    return True


def _phase_status(breaker, n_rows) -> str:
    """'partial' nếu giai đoạn dừng sớm vì sự cố (hết ngân sách / nguồn treo).
    Đủ hạn mức mã của lần chạy ("du_han_muc") là dừng BÌNH THƯỜNG → 'ok'."""
    if breaker.stopped and breaker.reason != "du_han_muc":
        return "partial"
    return "ok" if n_rows else "empty"


def _env_int(name):
    raw = os.getenv(name)
    return int(raw) if raw else None


def _order_by_fetch_age(con, dataset, symbols):
    """Mã CHƯA TỪNG nạp trước (theo chữ cái), rồi theo lần nạp gần nhất tăng dần.
    Dùng cho sự kiện DN khi nạp rải: mỗi lần chạy chỉ gọi một ít mã, nên phải
    xoay vòng để mọi mã lần lượt được làm mới (05/10/2026)."""
    st = warehouse.fetch_status(con, dataset)
    st = st[st["symbol"].isin(set(symbols))]
    seen = set(st["symbol"])
    never = sorted(s for s in symbols if s not in seen)
    return never + st.sort_values(["fetched_at", "symbol"], kind="mergesort")["symbol"].tolist()


COMPANY_MISSING_RETRY_DAYS = 7


def _symbols_missing_profile(con, symbols, now=None,
                             retry_days=COMPANY_MISSING_RETRY_DAYS):
    """Mã chưa có dòng nào trong raw_company_info, chưa từng dò trước, rồi dò cũ nhất.

    Hồ sơ DN chỉ nạp đủ ở job monthly, nên mã mới lên sàn không có ngành tới
    đầu tháng sau — lâu hơn nữa nếu monthly hỏng (huỷ vì quá giờ 01/09 + 01/10;
    DTR/KAI/GTX lên sàn 09/2026 làm test not_null của mart_sector_snapshot fail
    17/10/2026). Mã đã dò trong `retry_days` ngày bị bỏ qua: DPD/PYU/TAC nguồn
    trả rỗng thật, gọi lại mỗi lần trickle là phí lệnh của nguồn đang bị bóp."""
    have = {r[0] for r in con.execute("SELECT symbol FROM raw_company_info").fetchall()}
    missing = [s for s in symbols if s not in have]
    now = now or datetime.now()
    st = warehouse.fetch_status(con, "company_missing")
    recent = set(st.loc[st["fetched_at"] > now - timedelta(days=retry_days), "symbol"])
    return [s for s in _order_by_fetch_age(con, "company_missing", missing) if s not in recent]


def _portfolio_symbols() -> list[str]:
    cfg = yaml.safe_load(open(ROOT / "config" / "portfolio.yml", encoding="utf-8"))
    return [h["symbol"] for h in cfg["holdings"]]


EMPTY_PROBE_SKIP_DAYS = 30


def _order_statement_symbols(con, symbols, period, now=None,
                             empty_skip_days=EMPTY_PROBE_SKIP_DAYS):
    """Xếp mã cho bước BCTC chọn lọc. Trả (thứ tự, known).

    1. Mã chưa có BCTC trong kho và CHƯA TỪNG dò (theo chữ cái) — đứng đầu.
    2. Mã chưa có BCTC, lần dò gần nhất rỗng nhưng đã quá `empty_skip_days`
       ngày (cũ nhất trước). Dò rỗng trong `empty_skip_days` ngày → BỎ QUA hẳn:
       ~300 mã nguồn không có BCTC từng chiếm trọn lô đầu mỗi tuần (04/10/2026).
    3. Mã đã có BCTC, theo lần dò gần nhất tăng dần (cũ nhất trước).

    Đây là phần "xoay vòng" tối thiểu: job dừng giữa chừng thì lần sau tự làm
    tiếp từ các mã cũ nhất. known đưa thẳng vào fetch_financial_statements."""
    now = now or datetime.now()
    sym_set = set(symbols)
    fr = warehouse.statement_freshness(con, period)
    fr = fr[fr["symbol"].isin(sym_set)]
    have = set(fr["symbol"])
    ps = warehouse.statement_probe_status(con, period)
    ps = ps[ps["symbol"].isin(sym_set - have)].set_index("symbol")
    cutoff = pd.Timestamp(now - timedelta(days=empty_skip_days))
    never, stale_empty = [], []
    for sym in sorted(sym_set - have):
        if sym not in ps.index:
            never.append(sym)
        elif ps.loc[sym, "result"] == "empty" and pd.Timestamp(ps.loc[sym, "probed_at"]) > cutoff:
            continue
        else:
            stale_empty.append((pd.Timestamp(ps.loc[sym, "probed_at"]), sym))
    present = fr.sort_values(["probe_at", "symbol"], kind="mergesort")["symbol"].tolist()
    known = {r.symbol: {"latest_label": r.latest_label, "full_at": r.full_at}
             for r in fr.itertuples(index=False)}
    return never + [s for _, s in sorted(stale_empty)] + present, known


def _weekly_event_symbols(con, symbols, min_market_cap_vnd, portfolio):
    """Mã nạp sự kiện DN ở job TUẦN: vốn hoá ≥ ngưỡng (dim_stock) + danh mục.

    04/10/2026: nguồn bóp lưu lượng sau vài nghìn lệnh/ngày; sự kiện của ~1.000
    mã nhỏ/kém thanh khoản ít khi dùng trong phân tích. Ngưỡng 500 tỷ (~600 mã)
    bao trọn vũ trụ hồ sơ sàng lọc rộng nhất (deep_value). Job THÁNG vẫn quét
    mọi mã. Chưa có dim_stock (kho mới) → dùng mọi mã."""
    try:
        big = {r[0] for r in con.execute(
            "SELECT symbol FROM dim_stock WHERE market_cap >= ?", [min_market_cap_vnd]
        ).fetchall()}
    except Exception:
        return list(symbols)
    keep = big | set(portfolio)
    return [s for s in symbols if s in keep]


def _ingest_statements_chunked(con, symbols, source, period, deadline=None,
                               selective=False, stats=None, max_calls=None):
    """Fetch + ghi BCTC theo TỪNG LÔ STATEMENT_CHUNK_SIZE mã (fix trần 360
    phút CI — xem STATEMENT_CHUNK_SIZE).

    Trả về (tổng số dòng đã ghi, số lần gọi lỗi mạng/API, tổng số lần gọi).

    `selective=True` (spec 2026-10-04-bctc-chon-loc): xếp mã cũ nhất trước và
    chỉ tải đủ 3 báo cáo khi cần (xem fetch_financial_statements). `deadline`
    (time.monotonic): quá hạn thì dừng có kiểm soát. `stats` (dict, tuỳ chọn)
    nhận thêm: n_full, n_probe_only, n_symbols_done, stopped_early, stop_reason.

    Chữ ký fetch_financial_statements/upsert_financial_statements KHÔNG đổi
    với lời gọi mặc định — chỉ truyền tham số mới khi được bật, nên các test
    giả lập cũ vẫn chạy nguyên. Ghi theo lô: lô nào xong là dữ liệu nằm thật
    trong bảng; ngưỡng "degraded" của dq.status_for tính trên TỪNG LÔ.
    """
    stats = stats if stats is not None else {}
    stats.update(n_full=0, n_probe_only=0, n_symbols_done=0,
                 stopped_early=False, stop_reason=None)
    if not symbols:
        return 0, 0, 0
    known = None
    if selective:
        symbols, known = _order_statement_symbols(con, symbols, period)
    total_rows = n_errors = total_calls = 0
    n_chunks = (len(symbols) + STATEMENT_CHUNK_SIZE - 1) // STATEMENT_CHUNK_SIZE
    _log(f"Bắt đầu fetch BCTC chi tiết, period={period} ({len(symbols)} mã, "
         f"{n_chunks} lô x {STATEMENT_CHUNK_SIZE}"
         + (", chọn lọc: mã cũ nhất trước" if selective else "") + ")...")
    extra = {}
    if selective:
        extra["known"] = known
    if deadline is not None:
        extra["deadline"] = deadline
    for i in range(0, len(symbols), STATEMENT_CHUNK_SIZE):
        if max_calls is not None:
            if total_calls >= max_calls:
                stats.update(stopped_early=True, stop_reason="du_han_muc")
                break
            extra["max_calls"] = max_calls - total_calls
        if deadline is not None and time.monotonic() > deadline:
            stats.update(stopped_early=True, stop_reason="het_ngan_sach")
            break
        chunk = symbols[i:i + STATEMENT_CHUNK_SIZE]
        df = ingest_market.fetch_financial_statements(chunk, source, period=period, **extra)
        n_rows = warehouse.upsert_financial_statements(con, df)
        if selective and df.attrs.get("probes"):
            warehouse.record_statement_probes(con, period, df.attrs["probes"])
        total_rows += n_rows
        # n_errors/total_calls đi kèm DataFrame qua df.attrs — xem
        # fetch_financial_statements.
        n_errors += int(df.attrs.get("n_errors", 0))
        total_calls += int(df.attrs.get("total_calls", 0))
        for k in ("n_full", "n_probe_only"):
            stats[k] += int(df.attrs.get(k, 0))
        stats["n_symbols_done"] += int(df.attrs.get("n_symbols_done", len(chunk)))
        _log(f"[statements/{period}] lô {i // STATEMENT_CHUNK_SIZE + 1}/{n_chunks} "
             f"({len(chunk)} mã): +{n_rows} dòng, cộng dồn {total_rows} dòng, "
             f"{n_errors} lỗi mạng/API")
        if df.attrs.get("stopped_early"):
            stats.update(stopped_early=True, stop_reason=df.attrs.get("stop_reason"))
            break
    if stats["stopped_early"]:
        _log(f"[statements/{period}] DỪNG SỚM ({stats['stop_reason']}) sau "
             f"{stats['n_symbols_done']}/{len(symbols)} mã — lần sau làm tiếp từ mã cũ nhất.")
    return total_rows, n_errors, total_calls


def _symbols_need_year_fetch(con, symbols):
    """Loại khỏi `symbols` các mã đã có dữ liệu period_type='year' được ghi
    trong vòng STATEMENT_YEAR_FRESH_DAYS ngày (fix trần 360 phút CI).

    BCTC năm hiếm khi đổi, nên fetch lại hàng tháng cho mã đã có dữ liệu
    tươi gần như chắc chắn trả về đúng con số cũ — tốn thời gian mà không
    thêm thông tin. Mã CHƯA có dữ liệu year (kể cả mã VCI không có BCTC)
    vẫn được thử lại mỗi tháng: đó là cơ chế để dần lấp đầy các mã lỗi mạng
    thoáng qua ở lần chạy trước.
    """
    rows = con.execute(
        f"""
        SELECT DISTINCT symbol FROM raw_financial_statement
        WHERE period_type = 'year'
          AND ingested_at >= now() - INTERVAL {int(STATEMENT_YEAR_FRESH_DAYS)} DAY
        """
    ).fetchall()
    fresh = {r[0] for r in rows}
    need = [s for s in symbols if s not in fresh]
    _log(f"[statements/year] bỏ qua {len(symbols) - len(need)} mã đã có dữ liệu "
          f"year trong {STATEMENT_YEAR_FRESH_DAYS} ngày gần đây; "
          f"thực sự fetch {len(need)}/{len(symbols)} mã")
    return need


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Warehouse ingestion job")
    parser.add_argument(
        "--mode",
        choices=["daily", "weekly", "monthly"],
        default="daily",
        help="daily=giá EOD+universe; weekly=+financials; monthly=+company_info",
    )
    parser.add_argument(
        "--only",
        help=("Chỉ chạy các giai đoạn này (phân tách dấu phẩy), trong phạm vi --mode: "
              + ", ".join(PHASES) + ". Dùng để chạy lại phần còn thiếu khi một lần chạy "
              "bị dừng sớm — vd --mode weekly --only events,statements."),
    )
    args = parser.parse_args()
    only = _parse_only(args.only)

    key = os.getenv("VNSTOCK_API_KEY")
    if key:
        from vnstock import vnai
        vnai.setup_api_key(key)

    cfg = yaml.safe_load(open(ROOT / "config" / "warehouse.yml", encoding="utf-8"))
    source = cfg.get("source", "VCI")
    run_date = date.today().isoformat()
    deadline = _budget_deadline()

    con = warehouse.get_conn()
    warehouse.init_warehouse(con)

    # 1) Refresh danh sách mã
    uni = ingest_market.refresh_universe(cfg["exchanges"], source)
    n_sym = warehouse.upsert_symbols(con, uni, run_date)
    warehouse.log_load(con, f"warehouse_{args.mode}", "dim_symbols", n_sym,
                       "ok" if n_sym else "empty")
    _log(f"dim_symbols: {n_sym} mã ({', '.join(cfg['exchanges'])})")

    # 2) Giá EOD toàn thị trường (bulk) — mọi mode đều có
    symbols = warehouse.get_active_symbols(con)
    if not symbols:
        print("Chưa có mã nào trong dim_symbols — dừng.")
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_price_daily", 0,
                           "skipped", notes="no symbols")
        con.close()
        return

    if not _want(only, "prices"):
        pass
    elif not ingest_market.is_trading_day(date.today()):
        print(f"{run_date} không phải ngày giao dịch (T7/CN) — bỏ qua giá EOD.")
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_price_daily", 0,
                           "skipped", notes="non-trading day (weekend)")
    else:
        prices = ingest_market.fetch_eod_prices(symbols, source, cfg.get("price_board_batch", 50),
                                                run_date=run_date)
        board_date = prices.attrs.get("market_trading_date") if not prices.empty else None
        if board_date is not None and board_date != run_date:
            # Ngày lễ (T2–T6 nhưng sàn nghỉ): bảng giá vẫn mang phiên gần nhất.
            # Ghi vào sẽ tạo "phiên ma" (31/08–02/09/2026) — bỏ qua.
            print(f"{run_date}: bảng giá đang ở phiên {board_date} — ngày nghỉ, bỏ qua giá EOD.")
            warehouse.log_load(con, f"warehouse_{args.mode}", "raw_price_daily", 0,
                               "skipped", notes=f"holiday (board trading_date {board_date})")
        else:
            n_px = warehouse.upsert_prices(con, prices)
            failed = prices.attrs.get("failed_symbols", [])
            notes = None
            if failed:
                # Mã lỗi cả sau khi thử lại: ghi rõ để nạp bù (scripts/backfill_missing_days.py
                # --missing-only), không được báo ok như 05/10/2026.
                notes = (f"{len(failed)} ma loi nguon sau khi thu lai: "
                         + " ".join(failed[:60]) + (" …" if len(failed) > 60 else ""))
            status = "partial" if failed else ("ok" if n_px else "empty")
            warehouse.log_load(con, f"warehouse_{args.mode}", "raw_price_daily", n_px,
                               status, watermark=run_date, notes=notes)
            _log(f"raw_price_daily: {n_px}/{len(symbols)} mã có giá cho {run_date}"
                 + (f" — {len(failed)} mã lỗi nguồn, cần nạp bù" if failed else ""))

    # 2b) Chỉ số thị trường — mọi mode
    if _want(only, "index") and ingest_market.is_trading_day(date.today()):
        n_idx = 0
        for code in cfg.get("indices", []):
            idx_df = ingest_market.fetch_index_history(code, run_date, run_date, source)
            n_idx += warehouse.upsert_index_prices(con, idx_df)
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_index_daily", n_idx,
                           "ok" if n_idx else "empty", watermark=run_date)
        _log(f"raw_index_daily: {n_idx} dòng")

    # 2c) Tỷ giá VCB — mọi mode (D). 1 lần gọi API/ngày, rẻ. Bọc try/except:
    # đây là nguồn phụ, lỗi ở đây (vd VCB đổi tên cột) KHÔNG được phép chặn
    # các bước sau (đặc biệt BCTC monthly, đo thật 767 phút — xem
    # docs/B2-ket-qua-va-no-ky-thuat.md).
    try:
        if not _want(only, "fx"):
            raise _Skip()
        fx = ingest_market.fetch_exchange_rate(run_date)
        n_fx = warehouse.upsert_exchange_rate(con, fx)
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_exchange_rate",
                           n_fx, "ok" if n_fx else "empty", watermark=run_date)
        _log(f"raw_exchange_rate: {n_fx} dòng cho {run_date}")
    except _Skip:
        pass
    except Exception as e:
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_exchange_rate",
                           0, "degraded", watermark=run_date, notes=str(e)[:500])
        _log(f"raw_exchange_rate: LỖI ({e}) — bỏ qua, không chặn bước sau")

    # 2d) Tin tức 5 mã portfolio — mọi mode (D). Rẻ (5 mã), append-only.
    # Bọc try/except cùng lý do với 2c).
    try:
        if not _want(only, "news"):
            raise _Skip()
        portfolio_symbols = _portfolio_symbols()
        news = ingest_market.fetch_news(portfolio_symbols, source)
        n_news = warehouse.insert_news(con, news)
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_news",
                           n_news, "ok" if n_news else "empty", watermark=run_date,
                           notes=f"append-only; fetch {len(news)} dong")
        _log(f"raw_news: +{n_news} dòng mới (fetch {len(news)})")
    except _Skip:
        pass
    except Exception as e:
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_news",
                           0, "degraded", watermark=run_date, notes=str(e)[:500])
        _log(f"raw_news: LỖI ({e}) — bỏ qua, không chặn bước sau")

    # 3) Financial ratios — weekly và monthly
    if args.mode in ("weekly", "monthly") and _want(only, "ratios") and not _skip_for_budget(
            con, args.mode, "raw_financial_ratio", deadline, run_date):
        _log(f"Bắt đầu fetch financials ({len(symbols)} mã)...")
        br_fin = ingest.SourceBreaker("ratios", deadline=deadline)
        fin = ingest_market.fetch_financials(symbols, source, breaker=br_fin)
        n_fin = warehouse.upsert_financial_ratios(con, fin)
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_financial_ratio", n_fin,
                           _phase_status(br_fin, n_fin), watermark=run_date,
                           notes=br_fin.notes())
        _log(f"raw_financial_ratio: {n_fin} dòng")

    # 3a) Hồ sơ DN cho mã CHƯA CÓ hồ sơ — chỉ weekly (trickle chạy --mode weekly;
    # monthly đã có khối 4 nạp đủ). Đặt trước sự kiện/BCTC: vài lệnh, gọi khi
    # nguồn chưa bị bóp. Xem _symbols_missing_profile.
    if args.mode == "weekly" and _want(only, "company_missing") and not _skip_for_budget(
            con, args.mode, "raw_company_info", deadline, run_date):
        miss = _symbols_missing_profile(con, symbols)
        cap = _env_int("COMPANY_MISSING_MAX_SYMBOLS") or 10
        _log(f"Hồ sơ DN mã chưa có hồ sơ: {len(miss)} mã cần dò, tối đa {cap} mã lần này")
        if miss:
            br_miss = ingest.SourceBreaker("company_missing", deadline=deadline, max_symbols=cap)
            info = ingest_market.fetch_company_info(miss, source, breaker=br_miss)
            warehouse.record_fetches(con, "company_missing", br_miss.fetched)
            n_info = warehouse.upsert_company_info(con, info)
            warehouse.log_load(con, f"warehouse_{args.mode}", "raw_company_info", n_info,
                               _phase_status(br_miss, n_info), watermark=run_date,
                               notes=f"chi ma chua co ho so; {br_miss.notes()}")
            _log(f"raw_company_info (mã chưa có hồ sơ): {n_info}/{len(br_miss.fetched)} mã có hồ sơ")
            if n_info:
                warehouse.update_symbol_exchanges(con)

    # 3b) Sự kiện doanh nghiệp (B1) — chạy CẢ weekly lẫn monthly.
    # Weekly vì GDKHQ có ngày cụ thể, chạy tháng dễ lỡ sự kiện vừa công bố
    # vừa chốt quyền trong cùng tháng. Monthly cũng chạy vì nó là superset
    # của weekly (giống cách financials đã làm ở nhánh phía trên) — không
    # có lý do bỏ sót sự kiện DN riêng ở lần chạy tháng.
    if args.mode in ("weekly", "monthly") and _want(only, "events") and not _skip_for_budget(
            con, args.mode, "raw_corporate_event", deadline, run_date):
        ev_symbols = symbols
        if args.mode == "weekly":
            ev_symbols = _weekly_event_symbols(
                con, symbols, cfg.get("weekly_events_min_market_cap_vnd", 500_000_000_000),
                _portfolio_symbols())
        ev_symbols = _order_by_fetch_age(con, "events", ev_symbols)
        ev_cap = _env_int("EVENTS_MAX_SYMBOLS")
        _log(f"Bắt đầu fetch sự kiện DN ({len(ev_symbols)}/{len(symbols)} mã, cũ nhất trước"
             + (f", tối đa {ev_cap} mã lần này" if ev_cap else "") + ")...")
        br_ev = ingest.SourceBreaker("events", deadline=deadline, max_symbols=ev_cap)
        events = ingest_market.fetch_corporate_events(ev_symbols, source, breaker=br_ev)
        warehouse.record_fetches(con, "events", br_ev.fetched)
        n_ev = warehouse.insert_corporate_events(con, events)
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_corporate_event",
                           n_ev, _phase_status(br_ev, n_ev), watermark=run_date,
                           notes=f"append-only; fetch {len(events)} dong; {br_ev.notes()}")
        _log(f"raw_corporate_event: +{n_ev} dòng mới (fetch {len(events)})")

    # 4) Dim_industry (phân ngành ICB) + company info — monthly only
    if args.mode == "monthly" and _want(only, "company") and not _skip_for_budget(
            con, args.mode, "raw_company_info", deadline, run_date):
        ind = ingest_market.fetch_industries_icb(source)
        n_ind = warehouse.upsert_industries(con, ind)
        warehouse.log_load(con, f"warehouse_{args.mode}", "dim_industry", n_ind,
                           "ok" if n_ind else "empty", watermark=run_date)
        _log(f"dim_industry: {n_ind} ngành ICB")

        # Mã chưa nạp / nạp cũ nhất đi trước (18/10/2026): monthly bị huỷ giữa
        # chừng 01/09 + 01/10, mỗi lần lại bắt đầu từ chữ A — mã cuối bảng
        # chữ cái không bao giờ được làm mới. Xoay vòng như sự kiện DN.
        _log(f"Bắt đầu fetch company info ({len(symbols)} mã, cũ nhất trước)...")
        br_info = ingest.SourceBreaker("company_info", deadline=deadline)
        info = ingest_market.fetch_company_info(
            _order_by_fetch_age(con, "company_info", symbols), source, breaker=br_info)
        warehouse.record_fetches(con, "company_info", br_info.fetched)
        n_info = warehouse.upsert_company_info(con, info)
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_company_info", n_info,
                           _phase_status(br_info, n_info), watermark=run_date,
                           notes=br_info.notes())
        _log(f"raw_company_info: {n_info} mã")
        n_exch = warehouse.update_symbol_exchanges(con)
        warehouse.log_load(con, f"warehouse_{args.mode}", "dim_symbols", n_exch,
                           "ok" if n_exch else "empty", watermark=run_date,
                           notes="sync exchange tu raw_company_info")
        _log(f"dim_symbols.exchange: cập nhật {n_exch} mã")

        _log(f"Bắt đầu fetch cơ cấu sở hữu ({len(symbols)} mã)...")
        br_sh = ingest.SourceBreaker("shareholders", deadline=deadline)
        sh = ingest_market.fetch_shareholders(
            _order_by_fetch_age(con, "shareholders", symbols), source, run_date, breaker=br_sh)
        warehouse.record_fetches(con, "shareholders", br_sh.fetched)
        n_sh = warehouse.upsert_shareholders(con, sh)
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_shareholder",
                           n_sh, _phase_status(br_sh, n_sh), watermark=run_date,
                           notes=f"snapshot {run_date}; {br_sh.notes()}")
        _log(f"raw_shareholder: {n_sh} dòng (snapshot {run_date})")

        br_of = ingest.SourceBreaker("officers", deadline=deadline)
        of = ingest_market.fetch_officers(
            _order_by_fetch_age(con, "officers", symbols), source, run_date, breaker=br_of)
        warehouse.record_fetches(con, "officers", br_of.fetched)
        n_of = warehouse.upsert_officers(con, of)
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_officer",
                           n_of, _phase_status(br_of, n_of), watermark=run_date,
                           notes=f"snapshot {run_date}; {br_of.notes()}")
        _log(f"raw_officer: {n_of} dòng (snapshot {run_date})")

    # 5) BCTC chi tiết (B2) — quarter chạy CẢ weekly lẫn monthly, cùng lý
    # do sự kiện DN chạy cả hai (monthly là superset của weekly).
    #
    # FIX trần 360 phút của GitHub Actions (final review B2): khối BCTC CỐ Ý
    # xếp SAU khối 4 (dim_industry/company_info/shareholders/officers). Đo
    # thật ở Task 5: job monthly mất 767 phút — vượt xa trần CỨNG 360 phút
    # của GitHub-hosted runner, nên rất dễ bị GitHub giết giữa chừng. BCTC
    # là phần chậm nhất; nếu để nó chạy TRƯỚC như bản đầu thì một job bị
    # giết sẽ kéo theo mất luôn các bước ĐÃ CÓ TỪ TRƯỚC B2 (regression cho
    # chức năng cũ). Xếp sau -> các bước cũ luôn hoàn tất trước khi bước vào
    # phần rủi ro nhất.
    # Chọn lọc (spec 2026-10-04-bctc-chon-loc): dò báo cáo KQKD, chỉ tải đủ 3
    # báo cáo khi có kỳ mới / mã mới / quá 90 ngày; mã cũ nhất đi trước; dừng
    # có kiểm soát khi hết ngân sách hoặc nguồn treo.
    if args.mode in ("weekly", "monthly") and _want(only, "statements") and not _skip_for_budget(
            con, args.mode, "raw_financial_statement", deadline, run_date):
        st_q: dict = {}
        n_stmt_q, n_err_q, n_call_q = _ingest_statements_chunked(
            con, symbols, source, "quarter", deadline=deadline, selective=True, stats=st_q,
            max_calls=_env_int("STATEMENTS_MAX_CALLS"))
        status_q = ("partial" if st_q["stopped_early"] and st_q["stop_reason"] != "du_han_muc"
                    else ("ok" if n_stmt_q or st_q["n_symbols_done"] else "empty"))
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_financial_statement",
                           n_stmt_q, status_q, watermark=run_date,
                           notes=(f"period=quarter; {n_err_q}/{n_call_q} loi mang/API; "
                                  f"do {st_q['n_symbols_done']}/{len(symbols)} ma, "
                                  f"tai du {st_q['n_full']}"
                                  + (f"; dung som: {st_q['stop_reason']}"
                                     if st_q["stopped_early"] else "")))
        _log(f"raw_financial_statement (quarter): {n_stmt_q} dòng")

    # 5b) BCTC chi tiết, period=year — CHỈ monthly (dữ liệu năm hiếm khi
    # đổi, không cần nhịp tuần; xếp cùng nhịp với company_info/shareholders
    # bên trên thay vì chạy tuần vô ích). Thêm bước lọc mã đã có dữ liệu
    # year còn tươi — xem _symbols_need_year_fetch.
    if args.mode == "monthly" and _want(only, "statements_year") and not _skip_for_budget(
            con, args.mode, "raw_financial_statement", deadline, run_date):
        year_symbols = _symbols_need_year_fetch(con, symbols)
        st_y: dict = {}
        n_stmt_y, n_err_y, n_call_y = _ingest_statements_chunked(
            con, year_symbols, source, "year", deadline=deadline, stats=st_y)
        status_y = "partial" if st_y["stopped_early"] else ("ok" if n_stmt_y else "empty")
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_financial_statement",
                           n_stmt_y, status_y, watermark=run_date,
                           notes=(f"period=year; {n_err_y}/{n_call_y} loi mang/API; "
                                  f"fetch {len(year_symbols)}/{len(symbols)} ma"))
        _log(f"raw_financial_statement (year): {n_stmt_y} dòng")

    con.close()
    _log(f"Xong warehouse job ({args.mode}).")


if __name__ == "__main__":
    main()
