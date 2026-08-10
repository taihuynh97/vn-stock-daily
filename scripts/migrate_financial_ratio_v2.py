"""Migration: raw_financial_ratio 13 cột → 50 cột (bao gồm chỉ tiêu ngân hàng).

Raw layer tái tạo được từ API nên không chuyển đổi dữ liệu: đổi tên bảng cũ
thành backup, tạo bảng mới, nạp lại toàn bộ, đối chiếu, rồi mới xoá backup.

`step_verify` CHẶN xoá backup nếu có mã "mồ côi" — mã có trong backup nhưng
không nạp lại được (thường là mã đã hủy niêm yết, `get_active_symbols()`
không trả về). Đây là quyết định có chủ đích: backup được giữ lại vĩnh viễn
trong trường hợp đó để không mất dữ liệu 10 năm một cách âm thầm.

    export WAREHOUSE_DB=md:vn_market
    export motherduck_token=<token>
    export VNSTOCK_API_KEY=<key>          # nếu có, nâng rate limit lên 60 req/phút
    export VNSTOCK_MIN_INTERVAL=1.05      # nếu có key Community
    python -m scripts.migrate_financial_ratio_v2 --step rename
    python -m scripts.migrate_financial_ratio_v2 --step reload
    python -m scripts.migrate_financial_ratio_v2 --step verify
    python -m scripts.migrate_financial_ratio_v2 --step cleanup
"""
import os
import sys

# load_dotenv() PHẢI chạy trước khi import src.* — src.ingest đọc
# VNSTOCK_MIN_INTERVAL từ env ngay ở module scope lúc import, nên nếu
# .env được nạp sau import thì biến trong .env không có tác dụng.
from dotenv import load_dotenv

load_dotenv()

import argparse

from src import ingest_market, warehouse

JOB_NAME = "migration_financial_ratio_v3_50cols"
BACKUP = "raw_financial_ratio_v1_backup"


def _table_exists(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
        [name],
    ).fetchone()[0])


def step_rename(con):
    if _table_exists(con, BACKUP):
        print(f"{BACKUP} đã tồn tại — bỏ qua bước rename.")
        return
    n = con.execute("SELECT count(*) FROM raw_financial_ratio").fetchone()[0]
    con.execute(f"ALTER TABLE raw_financial_ratio RENAME TO {BACKUP}")
    warehouse.init_warehouse(con)
    warehouse.log_load(
        con, JOB_NAME, "raw_financial_ratio", 0, "ok",
        notes=f"DDL rename: raw_financial_ratio ({n} dong) -> {BACKUP}; "
              "tao lai raw_financial_ratio schema 50 cot",
    )
    print(f"Đã đổi tên bảng cũ ({n} dòng) → {BACKUP}, tạo bảng mới 50 cột.")


def step_reload(con):
    symbols = warehouse.get_active_symbols(con)
    print(f"Nạp lại tỷ số cho {len(symbols)} mã...")
    total = 0
    failed_chunks = 0
    failed_symbols = 0
    batch = 50
    for i in range(0, len(symbols), batch):
        chunk = symbols[i:i + batch]
        df = ingest_market.fetch_financials(chunk)
        if df.empty:
            failed_chunks += 1
            failed_symbols += len(chunk)
            print(f"  {i + len(chunk)}/{len(symbols)} mã — CHUNK LỖI (0 dòng "
                  f"trả về), tổng vẫn {total} dòng")
            continue
        # Một chunk có thể trả dữ liệu cho MỘT PHẦN số mã (API lỗi/rate-limit
        # giữa chừng) — nếu chỉ đếm chunk rỗng hoàn toàn thì các mã hụt trong
        # chunk "thành công" bị bỏ sót khỏi thống kê, status vẫn ghi "ok".
        got = df["symbol"].nunique()
        missing = len(chunk) - got
        if missing > 0:
            failed_symbols += missing
            print(f"  {i + len(chunk)}/{len(symbols)} mã — chunk thiếu "
                  f"{missing}/{len(chunk)} mã (trả {got}/{len(chunk)})")
        total += warehouse.upsert_financial_ratios(con, df)
        print(f"  {i + len(chunk)}/{len(symbols)} mã — tổng {total} dòng")

    if failed_symbols:
        status = "partial"
        notes = (
            f"reload 50 cot tu ratio_summary; {failed_chunks} batch loi hoan "
            f"toan, tong {failed_symbols} ma khong nap duoc trong lan chay nay"
        )
    else:
        status = "ok" if total else "empty"
        notes = "reload 50 cot tu ratio_summary"

    warehouse.log_load(con, JOB_NAME, "raw_financial_ratio", total, status,
                       notes=notes)
    print(f"Xong: {total} dòng. Batch lỗi hoàn toàn: {failed_chunks}. "
          f"Mã hụt: {failed_symbols}.")


def step_verify(con) -> bool:
    old_rows, old_syms = con.execute(
        f"SELECT count(*), count(DISTINCT symbol) FROM {BACKUP}"
    ).fetchone()
    new_rows, new_syms = con.execute(
        "SELECT count(*), count(DISTINCT symbol) FROM raw_financial_ratio"
    ).fetchone()
    active_syms = con.execute(
        "SELECT count(*) FROM dim_symbols WHERE is_active"
    ).fetchone()[0]
    orphan_count, orphan_list = con.execute(
        f"""
        SELECT count(*), string_agg(symbol, ', ') FROM (
            SELECT DISTINCT symbol FROM {BACKUP}
            EXCEPT
            SELECT DISTINCT symbol FROM raw_financial_ratio
        )
        """
    ).fetchone()

    print(f"cũ : {old_rows} dòng / {old_syms} mã")
    print(f"mới: {new_rows} dòng / {new_syms} mã")
    print(f"mã đang hoạt động (dim_symbols.is_active): {active_syms}")

    checks = [
        new_syms >= old_syms * 0.95,
        new_rows >= old_rows,
        # Sàn tuyệt đối: không chỉ so tương đối với backup (backup có thể vốn
        # đã thiếu từ trước), mà còn phải so với chính dim_symbols hiện tại.
        new_syms >= active_syms * 0.95,
    ]

    if orphan_count:
        print(
            f"\n{orphan_count} mã có trong {BACKUP} nhưng KHÔNG có trong bảng "
            f"mới: {orphan_list}"
        )
        print(
            "Đây thường là các mã đã hủy niêm yết mà get_active_symbols() "
            "không trả về nên không được reload — ĐÂY LÀ KẾT QUẢ MONG ĐỢI của "
            "việc backup được giữ lại có chủ đích để không mất dữ liệu, "
            "KHÔNG PHẢI lỗi cần sửa. Không cần tìm cách cho verify ĐẠT trong "
            "trường hợp này — backup sẽ tiếp tục được giữ lại."
        )
        checks.append(False)
    else:
        print(f"Không có mã mồ côi: mọi mã trong {BACKUP} đều có trong bảng mới.")

    company_info_rows = con.execute(
        "SELECT count(*) FROM raw_company_info"
    ).fetchone()[0]
    bank_rows = con.execute(
        "SELECT count(*) FROM raw_company_info WHERE is_bank"
    ).fetchone()[0]
    if company_info_rows == 0 or bank_rows == 0:
        # raw_company_info chỉ được nạp ở build_warehouse.py --mode monthly,
        # chạy SAU verify trong thứ tự của plan — không đảo thứ tự vì monthly
        # build cũng gọi lại fetch_financials, tốn thêm 28–82 phút vô ích.
        # Vì vậy chỉ tiêu ngân hàng ở đây là kiểm tra MỀM: không đánh giá được
        # thì bỏ qua, không tính là fail.
        print(
            "raw_company_info chưa nạp (hoặc chưa có mã nào is_bank) — không "
            "đánh giá được chỉ tiêu ngân hàng ở bước này; sẽ được kiểm ở bước "
            "nghiệm thu sau khi đã nạp company_info."
        )
    else:
        banks_ok = con.execute(
            """
            SELECT count(*) FROM raw_financial_ratio f
            JOIN raw_company_info c USING (symbol)
            WHERE c.is_bank AND f.net_interest_margin IS NOT NULL
              AND f.net_interest_margin <> 0
            """
        ).fetchone()[0]
        print(f"dòng ngân hàng có net_interest_margin thật: {banks_ok}")
        checks.append(banks_ok > 0)

    ok = all(checks)
    print("ĐẠT" if ok else "KHÔNG ĐẠT — không được xoá backup")
    return ok


def step_cleanup(con) -> bool:
    if not step_verify(con):
        print("Bỏ qua cleanup vì verify không đạt.")
        return False
    n = con.execute(f"SELECT count(*) FROM {BACKUP}").fetchone()[0]
    con.execute(f"DROP TABLE {BACKUP}")
    warehouse.log_load(
        con, JOB_NAME, "raw_financial_ratio", 0, "ok",
        notes=f"DDL cleanup: da xoa {BACKUP} ({n} dong) sau khi verify DAT",
    )
    print(f"Đã xoá {BACKUP}.")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--step",
                        choices=["rename", "reload", "verify", "cleanup"],
                        required=True)
    args = parser.parse_args()

    # Không đăng ký key thì chạy ở bậc Guest 20 req/phút — đặt
    # VNSTOCK_MIN_INTERVAL=1.05 (khuyến nghị ở docstring trên) mà thiếu khối
    # này sẽ vượt rate limit ngay (step_reload gọi fetch_financials rất nhiều).
    key = os.getenv("VNSTOCK_API_KEY")
    if key:
        from vnstock import vnai
        vnai.setup_api_key(key)

    db_target = os.getenv("WAREHOUSE_DB", warehouse.DEFAULT_DB)
    print(f"Đang kết nối tới: {db_target}")

    con = warehouse.get_conn()
    warehouse.init_warehouse(con)
    fn = {"rename": step_rename, "reload": step_reload,
          "verify": step_verify, "cleanup": step_cleanup}[args.step]
    result = fn(con)
    con.close()

    if result is False:
        sys.exit(1)


if __name__ == "__main__":
    main()
