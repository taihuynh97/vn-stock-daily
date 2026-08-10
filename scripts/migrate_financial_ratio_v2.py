"""Migration: raw_financial_ratio 13 cột → 50 cột (bao gồm chỉ tiêu ngân hàng).

Raw layer tái tạo được từ API nên không chuyển đổi dữ liệu: đổi tên bảng cũ
thành backup, tạo bảng mới, nạp lại toàn bộ, đối chiếu, rồi mới xoá backup.

    export WAREHOUSE_DB=md:vn_market
    export motherduck_token=<token>
    export VNSTOCK_MIN_INTERVAL=1.05      # nếu có key Community
    python -m scripts.migrate_financial_ratio_v2 --step rename
    python -m scripts.migrate_financial_ratio_v2 --step reload
    python -m scripts.migrate_financial_ratio_v2 --step verify
    python -m scripts.migrate_financial_ratio_v2 --step cleanup
"""
import argparse

from dotenv import load_dotenv

from src import ingest_market, warehouse

load_dotenv()

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
    print(f"Đã đổi tên bảng cũ ({n} dòng) → {BACKUP}, tạo bảng mới 50 cột.")


def step_reload(con):
    symbols = warehouse.get_active_symbols(con)
    print(f"Nạp lại tỷ số cho {len(symbols)} mã...")
    total = 0
    batch = 50
    for i in range(0, len(symbols), batch):
        chunk = symbols[i:i + batch]
        df = ingest_market.fetch_financials(chunk)
        total += warehouse.upsert_financial_ratios(con, df)
        print(f"  {i + len(chunk)}/{len(symbols)} mã — tổng {total} dòng")
    warehouse.log_load(con, JOB_NAME, "raw_financial_ratio", total,
                       "ok" if total else "empty",
                       notes="reload 50 cot tu ratio_summary")
    print(f"Xong: {total} dòng.")


def step_verify(con) -> bool:
    old_rows, old_syms = con.execute(
        f"SELECT count(*), count(DISTINCT symbol) FROM {BACKUP}"
    ).fetchone()
    new_rows, new_syms = con.execute(
        "SELECT count(*), count(DISTINCT symbol) FROM raw_financial_ratio"
    ).fetchone()
    banks_ok = con.execute(
        """
        SELECT count(*) FROM raw_financial_ratio f
        JOIN raw_company_info c USING (symbol)
        WHERE c.is_bank AND f.net_interest_margin IS NOT NULL
          AND f.net_interest_margin <> 0
        """
    ).fetchone()[0]

    print(f"cũ : {old_rows} dòng / {old_syms} mã")
    print(f"mới: {new_rows} dòng / {new_syms} mã")
    print(f"dòng ngân hàng có net_interest_margin thật: {banks_ok}")

    ok = new_syms >= old_syms * 0.95 and new_rows >= old_rows and banks_ok > 0
    print("ĐẠT" if ok else "KHÔNG ĐẠT — không được xoá backup")
    return ok


def step_cleanup(con):
    if not step_verify(con):
        print("Bỏ qua cleanup vì verify không đạt.")
        return
    con.execute(f"DROP TABLE {BACKUP}")
    print(f"Đã xoá {BACKUP}.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--step",
                        choices=["rename", "reload", "verify", "cleanup"],
                        required=True)
    args = parser.parse_args()

    con = warehouse.get_conn()
    warehouse.init_warehouse(con)
    {"rename": step_rename, "reload": step_reload,
     "verify": step_verify, "cleanup": step_cleanup}[args.step](con)
    con.close()


if __name__ == "__main__":
    main()
