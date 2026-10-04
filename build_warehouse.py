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
from datetime import date, datetime, timezone
from pathlib import Path
import yaml
from dotenv import load_dotenv

from src import ingest_market, warehouse

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


def _ingest_statements_chunked(con, symbols, source, period):
    """Fetch + ghi BCTC theo TỪNG LÔ STATEMENT_CHUNK_SIZE mã (fix trần 360
    phút CI — xem STATEMENT_CHUNK_SIZE).

    Trả về (tổng số dòng đã ghi, số lần gọi lỗi mạng/API, tổng số lần gọi).

    Chữ ký fetch_financial_statements/upsert_financial_statements KHÔNG đổi
    — chỉ CÁCH GỌI đổi (vòng lặp theo lô), nên toàn bộ test Task 2 giữ
    nguyên. Lưu ý một hệ quả có thật: ngưỡng "degraded" của dq.status_for
    bên trong fetch_financial_statements giờ tính TRÊN TỪNG LÔ (~300 lần
    gọi) thay vì trên cả mẻ ~4.800 lần gọi — nhạy hơn (phát hiện nguồn đổi
    schema sớm hơn) và khi nó ném lỗi thì các lô trước đó vẫn giữ nguyên dữ
    liệu đã ghi, thay vì mất trắng.
    """
    if not symbols:
        return 0, 0, 0
    total_rows = n_errors = total_calls = 0
    n_chunks = (len(symbols) + STATEMENT_CHUNK_SIZE - 1) // STATEMENT_CHUNK_SIZE
    _log(f"Bắt đầu fetch BCTC chi tiết, period={period} ({len(symbols)} mã, "
          f"{n_chunks} lô x {STATEMENT_CHUNK_SIZE})...")
    for i in range(0, len(symbols), STATEMENT_CHUNK_SIZE):
        chunk = symbols[i:i + STATEMENT_CHUNK_SIZE]
        df = ingest_market.fetch_financial_statements(chunk, source, period=period)
        n_rows = warehouse.upsert_financial_statements(con, df)
        total_rows += n_rows
        # n_errors/total_calls đi kèm DataFrame qua df.attrs — xem
        # fetch_financial_statements (giữ nguyên kiểu trả về DataFrame để
        # không phải sửa mọi chỗ gọi/test hiện có).
        n_errors += int(df.attrs.get("n_errors", 0))
        total_calls += int(df.attrs.get("total_calls", 0))
        _log(f"[statements/{period}] lô {i // STATEMENT_CHUNK_SIZE + 1}/{n_chunks} "
              f"({len(chunk)} mã): +{n_rows} dòng, cộng dồn {total_rows} dòng, "
              f"{n_errors} lỗi mạng/API")
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
    args = parser.parse_args()

    key = os.getenv("VNSTOCK_API_KEY")
    if key:
        from vnstock import vnai
        vnai.setup_api_key(key)

    cfg = yaml.safe_load(open(ROOT / "config" / "warehouse.yml", encoding="utf-8"))
    source = cfg.get("source", "VCI")
    run_date = date.today().isoformat()

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

    if not ingest_market.is_trading_day(date.today()):
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
            warehouse.log_load(con, f"warehouse_{args.mode}", "raw_price_daily", n_px,
                               "ok" if n_px else "empty", watermark=run_date)
            _log(f"raw_price_daily: {n_px}/{len(symbols)} mã có giá cho {run_date}")

    # 2b) Chỉ số thị trường — mọi mode
    if ingest_market.is_trading_day(date.today()):
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
        fx = ingest_market.fetch_exchange_rate(run_date)
        n_fx = warehouse.upsert_exchange_rate(con, fx)
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_exchange_rate",
                           n_fx, "ok" if n_fx else "empty", watermark=run_date)
        _log(f"raw_exchange_rate: {n_fx} dòng cho {run_date}")
    except Exception as e:
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_exchange_rate",
                           0, "degraded", watermark=run_date, notes=str(e)[:500])
        _log(f"raw_exchange_rate: LỖI ({e}) — bỏ qua, không chặn bước sau")

    # 2d) Tin tức 5 mã portfolio — mọi mode (D). Rẻ (5 mã), append-only.
    # Bọc try/except cùng lý do với 2c).
    try:
        portfolio_cfg = yaml.safe_load(open(ROOT / "config" / "portfolio.yml", encoding="utf-8"))
        portfolio_symbols = [h["symbol"] for h in portfolio_cfg["holdings"]]
        news = ingest_market.fetch_news(portfolio_symbols, source)
        n_news = warehouse.insert_news(con, news)
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_news",
                           n_news, "ok" if n_news else "empty", watermark=run_date,
                           notes=f"append-only; fetch {len(news)} dong")
        _log(f"raw_news: +{n_news} dòng mới (fetch {len(news)})")
    except Exception as e:
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_news",
                           0, "degraded", watermark=run_date, notes=str(e)[:500])
        _log(f"raw_news: LỖI ({e}) — bỏ qua, không chặn bước sau")

    # 3) Financial ratios — weekly và monthly
    if args.mode in ("weekly", "monthly"):
        _log(f"Bắt đầu fetch financials ({len(symbols)} mã)...")
        fin = ingest_market.fetch_financials(symbols, source)
        n_fin = warehouse.upsert_financial_ratios(con, fin)
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_financial_ratio", n_fin,
                           "ok" if n_fin else "empty", watermark=run_date)
        _log(f"raw_financial_ratio: {n_fin} dòng")

    # 3b) Sự kiện doanh nghiệp (B1) — chạy CẢ weekly lẫn monthly.
    # Weekly vì GDKHQ có ngày cụ thể, chạy tháng dễ lỡ sự kiện vừa công bố
    # vừa chốt quyền trong cùng tháng. Monthly cũng chạy vì nó là superset
    # của weekly (giống cách financials đã làm ở nhánh phía trên) — không
    # có lý do bỏ sót sự kiện DN riêng ở lần chạy tháng.
    if args.mode in ("weekly", "monthly"):
        _log(f"Bắt đầu fetch sự kiện DN ({len(symbols)} mã)...")
        events = ingest_market.fetch_corporate_events(symbols, source)
        n_ev = warehouse.insert_corporate_events(con, events)
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_corporate_event",
                           n_ev, "ok" if n_ev else "empty", watermark=run_date,
                           notes=f"append-only; fetch {len(events)} dong")
        _log(f"raw_corporate_event: +{n_ev} dòng mới (fetch {len(events)})")

    # 4) Dim_industry (phân ngành ICB) + company info — monthly only
    if args.mode == "monthly":
        ind = ingest_market.fetch_industries_icb(source)
        n_ind = warehouse.upsert_industries(con, ind)
        warehouse.log_load(con, f"warehouse_{args.mode}", "dim_industry", n_ind,
                           "ok" if n_ind else "empty", watermark=run_date)
        _log(f"dim_industry: {n_ind} ngành ICB")

        _log(f"Bắt đầu fetch company info ({len(symbols)} mã)...")
        info = ingest_market.fetch_company_info(symbols, source)
        n_info = warehouse.upsert_company_info(con, info)
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_company_info", n_info,
                           "ok" if n_info else "empty", watermark=run_date)
        _log(f"raw_company_info: {n_info} mã")
        n_exch = warehouse.update_symbol_exchanges(con)
        warehouse.log_load(con, f"warehouse_{args.mode}", "dim_symbols", n_exch,
                           "ok" if n_exch else "empty", watermark=run_date,
                           notes="sync exchange tu raw_company_info")
        _log(f"dim_symbols.exchange: cập nhật {n_exch} mã")

        _log(f"Bắt đầu fetch cơ cấu sở hữu ({len(symbols)} mã)...")
        sh = ingest_market.fetch_shareholders(symbols, source, run_date)
        n_sh = warehouse.upsert_shareholders(con, sh)
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_shareholder",
                           n_sh, "ok" if n_sh else "empty", watermark=run_date,
                           notes=f"snapshot {run_date}")
        _log(f"raw_shareholder: {n_sh} dòng (snapshot {run_date})")

        of = ingest_market.fetch_officers(symbols, source, run_date)
        n_of = warehouse.upsert_officers(con, of)
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_officer",
                           n_of, "ok" if n_of else "empty", watermark=run_date,
                           notes=f"snapshot {run_date}")
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
    if args.mode in ("weekly", "monthly"):
        n_stmt_q, n_err_q, n_call_q = _ingest_statements_chunked(
            con, symbols, source, "quarter")
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_financial_statement",
                           n_stmt_q, "ok" if n_stmt_q else "empty", watermark=run_date,
                           notes=f"period=quarter; {n_err_q}/{n_call_q} loi mang/API")
        _log(f"raw_financial_statement (quarter): {n_stmt_q} dòng")

    # 5b) BCTC chi tiết, period=year — CHỈ monthly (dữ liệu năm hiếm khi
    # đổi, không cần nhịp tuần; xếp cùng nhịp với company_info/shareholders
    # bên trên thay vì chạy tuần vô ích). Thêm bước lọc mã đã có dữ liệu
    # year còn tươi — xem _symbols_need_year_fetch.
    if args.mode == "monthly":
        year_symbols = _symbols_need_year_fetch(con, symbols)
        n_stmt_y, n_err_y, n_call_y = _ingest_statements_chunked(
            con, year_symbols, source, "year")
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_financial_statement",
                           n_stmt_y, "ok" if n_stmt_y else "empty", watermark=run_date,
                           notes=(f"period=year; {n_err_y}/{n_call_y} loi mang/API; "
                                  f"fetch {len(year_symbols)}/{len(symbols)} ma"))
        _log(f"raw_financial_statement (year): {n_stmt_y} dòng")

    con.close()
    _log(f"Xong warehouse job ({args.mode}).")


if __name__ == "__main__":
    main()
