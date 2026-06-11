"""Migration một lần: cập nhật schema raw_financial_ratio sang dạng mới
(symbol, year, quarter, period_type, market_cap, pe, pb, ps, dividend_yield,
roe, roa, roic, debt_to_equity, current_ratio, gross_margin, ebit_margin,
after_tax_profit_margin) — phục vụ fetch_financials() mới dùng
Company.ratio_summary() thay vì Finance.ratio() (đang lỗi, bảng cũ 0 dòng).

Vì bảng cũ trên MotherDuck đang có 0 dòng (Phase 2A chưa từng chạy thành công),
migration chỉ cần DROP TABLE rồi để init_warehouse() tạo lại theo schema mới —
không cần chuyển đổi dữ liệu.

Có guard chống chạy lại 2 lần (tra etl_load_log).

Chạy 1 lần:
    export WAREHOUSE_DB=md:vn_market
    export motherduck_token=<token>
    python -m scripts.migrate_financial_ratio_schema
"""
from dotenv import load_dotenv

from src import warehouse

load_dotenv()

JOB_NAME = "migration_financial_ratio_schema_v2"


def main():
    con = warehouse.get_conn()

    already_run = con.execute(
        "SELECT count(*) FROM etl_load_log WHERE job_name = ? AND status = 'ok'",
        [JOB_NAME],
    ).fetchone()[0]
    if already_run:
        print(f"Migration '{JOB_NAME}' đã chạy trước đó — bỏ qua.")
        con.close()
        return

    before = con.execute("SELECT count(*) FROM raw_financial_ratio").fetchone()[0]
    print(f"Trước migration: raw_financial_ratio có {before} dòng.")
    if before > 0:
        print("CẢNH BÁO: bảng không rỗng — dừng lại, kiểm tra thủ công trước khi xoá.")
        con.close()
        return

    con.execute("DROP TABLE raw_financial_ratio;")
    warehouse.init_warehouse(con)
    print("Đã tạo lại raw_financial_ratio theo schema mới.")

    warehouse.log_load(
        con, JOB_NAME, "raw_financial_ratio", 0, "ok",
        notes="Drop + recreate raw_financial_ratio voi schema moi "
              "(year/quarter/period_type + cac chi so ratio_summary)",
    )
    con.close()
    print("Xong.")


if __name__ == "__main__":
    main()
