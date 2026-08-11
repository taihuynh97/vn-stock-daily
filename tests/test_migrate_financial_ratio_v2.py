"""Test cho scripts/migrate_financial_ratio_v2.py — tập trung vào logic phá
hủy (rename/cleanup) sắp chạy lên production 10 năm dữ liệu.

step_rename/step_verify/step_cleanup: thuần SQL trên DuckDB tạm, không gọi
API. step_reload: mock ingest_market.fetch_financials (không gọi API thật)
chỉ để kiểm chứng riêng hành vi bắt lỗi theo chunk (C2/review cuối) —
KHÔNG test toàn bộ luồng reload thật (cần API).
"""
from unittest.mock import patch

import duckdb
import pandas as pd
import pytest

from src import dq
from src import warehouse as wh
from scripts import migrate_financial_ratio_v2 as mig


def _seed(tmp_path):
    con = duckdb.connect(str(tmp_path / "mig.duckdb"))
    wh.init_warehouse(con)
    return con


def test_table_exists_ignores_same_named_table_in_other_attached_catalog(tmp_path):
    """I2 (review cuối) — kịch bản hỏng nguy hiểm nhất mà reviewer nêu: nếu
    _table_exists() không lọc catalog/schema hiện tại, step_rename có thể
    tưởng BACKUP đã tồn tại (thật ra chỉ tồn tại ở MỘT DATABASE KHÁC được
    ATTACH, vd. sample_data mà MotherDuck tự ATTACH cho mọi kết nối) rồi bỏ
    qua rename; sau đó step_verify truy vấn `{BACKUP}` không qualify catalog
    có thể đọc nhầm sang bảng đó, dẫn tới quyết định DROP TABLE dựa trên số
    liệu sai."""
    con = _seed(tmp_path)
    con.execute("ATTACH ':memory:' AS other_db")
    con.execute(f"CREATE TABLE other_db.main.{mig.BACKUP} (symbol VARCHAR)")

    # BACKUP KHÔNG tồn tại trong database hiện tại -- chỉ tồn tại ở other_db.
    assert mig._table_exists(con, mig.BACKUP) is False
    con.close()


def test_step_rename_twice_does_not_overwrite_backup(tmp_path):
    con = _seed(tmp_path)
    con.execute(
        "INSERT INTO raw_financial_ratio (symbol, year, quarter, period_type, "
        "loaded_at) VALUES ('AAA', 2025, 1, 'quarter', now())"
    )

    mig.step_rename(con)  # lần 1: AAA -> backup, tạo bảng mới rỗng
    assert con.execute(f"SELECT count(*) FROM {mig.BACKUP}").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM raw_financial_ratio").fetchone()[0] == 0

    # giả lập step_reload: nạp 1 mã khác vào bảng mới
    con.execute(
        "INSERT INTO raw_financial_ratio (symbol, year, quarter, period_type, "
        "loaded_at) VALUES ('BBB', 2025, 1, 'quarter', now())"
    )

    mig.step_rename(con)  # lần 2: phải bỏ qua vì backup đã tồn tại

    backup_symbols = {r[0] for r in con.execute(
        f"SELECT symbol FROM {mig.BACKUP}"
    ).fetchall()}
    new_symbols = {r[0] for r in con.execute(
        "SELECT symbol FROM raw_financial_ratio"
    ).fetchall()}
    assert backup_symbols == {"AAA"}   # backup KHÔNG bị đè
    assert new_symbols == {"BBB"}      # bảng mới cũng không bị đổi đi đâu
    con.close()


def _seed_with_delisted_symbol(con, n_active=20):
    """Mô phỏng kịch bản Critical: backup có n_active mã đang hoạt động +
    1 mã đã hủy niêm yết (OLD1, không có trong dim_symbols).
    """
    for i in range(1, n_active + 1):
        sym = f"S{i:03d}"
        con.execute(
            "INSERT INTO dim_symbols (symbol, exchange, company_name, "
            "is_active, first_seen, last_seen) VALUES "
            "(?, 'HOSE', ?, TRUE, DATE '2020-01-01', DATE '2026-08-07')",
            [sym, sym],
        )
        con.execute(
            "INSERT INTO raw_financial_ratio (symbol, year, quarter, "
            "period_type, loaded_at) VALUES (?, 2025, 1, 'quarter', now())",
            [sym],
        )
    con.execute(
        "INSERT INTO raw_financial_ratio (symbol, year, quarter, period_type, "
        "loaded_at) VALUES ('OLD1', 2020, 1, 'quarter', now())"
    )


def test_step_cleanup_refuses_when_backup_has_orphan_symbols(tmp_path, capsys):
    con = _seed(tmp_path)
    _seed_with_delisted_symbol(con, n_active=20)

    mig.step_rename(con)  # backup: 20 mã active + OLD1 = 21 mã, 21 dòng

    # giả lập reload: get_active_symbols() chỉ trả 20 mã active, KHÔNG có
    # OLD1 -> OLD1 trở thành mã "mồ côi" trong backup. Nạp nhiều hơn số dòng
    # cũ để các điều kiện count cũ (new_rows>=old_rows, new_syms>=95%*old_syms)
    # đều ĐẠT — chỉ có kiểm tra mã mồ côi mới chặn được cleanup.
    for i in range(1, 21):
        sym = f"S{i:03d}"
        con.execute(
            "INSERT INTO raw_financial_ratio (symbol, year, quarter, "
            "period_type, loaded_at) VALUES "
            "(?, 2025, 1, 'quarter', now()), (?, 2025, 2, 'quarter', now())",
            [sym, sym],
        )

    result = mig.step_cleanup(con)
    out = capsys.readouterr().out

    assert result is False
    assert mig._table_exists(con, mig.BACKUP) is True   # backup KHÔNG bị xoá
    assert "OLD1" in out   # log phải nêu rõ mã mồ côi
    con.close()


def test_step_cleanup_drops_backup_when_no_orphans(tmp_path):
    con = _seed(tmp_path)
    con.execute(
        "INSERT INTO dim_symbols (symbol, exchange, company_name, is_active, "
        "first_seen, last_seen) VALUES "
        "('AAA','HOSE','A',TRUE,DATE '2020-01-01',DATE '2026-08-07')"
    )
    con.execute(
        "INSERT INTO raw_financial_ratio (symbol, year, quarter, period_type, "
        "loaded_at) VALUES ('AAA', 2025, 1, 'quarter', now())"
    )
    mig.step_rename(con)   # backup: AAA (1 dòng)

    # reload lại đúng AAA, không thiếu mã nào
    con.execute(
        "INSERT INTO raw_financial_ratio (symbol, year, quarter, period_type, "
        "loaded_at) VALUES ('AAA', 2025, 1, 'quarter', now())"
    )

    result = mig.step_cleanup(con)

    assert result is True
    assert mig._table_exists(con, mig.BACKUP) is False   # backup đã bị xoá
    con.close()


def test_main_self_heals_after_interrupted_rename(tmp_path, monkeypatch):
    """Mô phỏng bị ngắt giữa ALTER TABLE và init_warehouse() trong
    step_rename: bảng cũ đã đổi tên thành backup nhưng raw_financial_ratio
    chưa được tạo lại. Gọi lại main() (bất kỳ --step nào) phải tự phục hồi
    vì main() luôn gọi init_warehouse(con) trước khi dispatch."""
    db_path = tmp_path / "mig.duckdb"
    con = duckdb.connect(str(db_path))
    wh.init_warehouse(con)
    con.execute(
        "INSERT INTO raw_financial_ratio (symbol, year, quarter, period_type, "
        "loaded_at) VALUES ('AAA', 2025, 1, 'quarter', now())"
    )
    # ngắt NGAY SAU ALTER TABLE, TRƯỚC init_warehouse():
    con.execute(f"ALTER TABLE raw_financial_ratio RENAME TO {mig.BACKUP}")
    assert not mig._table_exists(con, "raw_financial_ratio")
    con.close()

    monkeypatch.setenv("WAREHOUSE_DB", str(db_path))
    monkeypatch.setattr(
        "sys.argv", ["migrate_financial_ratio_v2.py", "--step", "verify"]
    )

    with pytest.raises(SystemExit):   # verify thất bại (bảng mới rỗng) -> exit 1
        mig.main()

    con2 = duckdb.connect(str(db_path))
    assert mig._table_exists(con2, "raw_financial_ratio") is True
    cols = {r[0] for r in con2.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'raw_financial_ratio'"
    ).fetchall()}
    assert "net_interest_margin" in cols   # bảng mới đúng schema 50 cột
    con2.close()


def _ratio_df_for(symbols):
    """DataFrame hợp lệ theo schema RATIO_ALL_COLS cho một danh sách mã —
    dùng để mock ingest_market.fetch_financials() trong test step_reload."""
    rows = []
    for sym in symbols:
        row = {
            "symbol": sym, "year": 2025, "quarter": 1,
            "period_type": "quarter", "ratio_type": "RATIO_TTM",
        }
        row.update({col: None for col in wh.RATIO_NUM_COLS})
        rows.append(row)
    return pd.DataFrame(rows)[wh.RATIO_ALL_COLS]


def _seed_active_symbols(con, n):
    for i in range(1, n + 1):
        sym = f"S{i:03d}"
        con.execute(
            "INSERT INTO dim_symbols (symbol, exchange, company_name, "
            "is_active, first_seen, last_seen) VALUES "
            "(?, 'HOSE', ?, TRUE, DATE '2020-01-01', DATE '2026-08-07')",
            [sym, sym],
        )


def test_step_reload_chunk_schema_error_does_not_abort_other_chunks(tmp_path, capsys):
    """C2 (áp dụng cho step_reload): fetch_financials có thể raise
    dq.SchemaError khi tỉ lệ mã sai schema trong MỘT chunk vượt ngưỡng
    degraded. Trước bản sửa này, exception đó thoát thẳng khỏi step_reload
    và giết cả bước reload — kể cả các chunk khác đã/sẽ nạp thành công."""
    con = _seed(tmp_path)
    _seed_active_symbols(con, 60)   # 2 chunk (batch=50): 50 + 10 mã

    good_chunk_symbols = [f"S{i:03d}" for i in range(51, 61)]

    def fake_fetch_financials(chunk, source="VCI"):
        if len(chunk) == 50:
            raise dq.SchemaError("[Company.ratio_summary] 40/50 mã sai schema")
        return _ratio_df_for(chunk)

    with patch(
        "src.ingest_market.fetch_financials", side_effect=fake_fetch_financials
    ):
        mig.step_reload(con)

    out = capsys.readouterr().out
    stored_symbols = {
        r[0] for r in con.execute("SELECT symbol FROM raw_financial_ratio").fetchall()
    }
    con.close()
    assert "CHUNK LỖI" in out
    assert "SchemaError" in out
    # chunk lỗi (50 mã đầu) không được nạp, nhưng chunk tốt (10 mã sau) vẫn
    # phải được nạp -- đây là điều quan trọng nhất: một chunk lỗi không giết
    # cả bước reload.
    assert stored_symbols == set(good_chunk_symbols)


def test_step_rename_skip_prints_row_counts_of_both_tables(tmp_path, capsys):
    """Minor đi kèm review cuối: nhánh 'bỏ qua rename' phải in số dòng của
    CẢ HAI bảng (BACKUP và raw_financial_ratio hiện tại), để vận hành phân
    biệt được 'đã migrate xong' (raw_financial_ratio có dữ liệu) với 'backup
    sót lại từ lần thử trước' (raw_financial_ratio rỗng/ít dòng)."""
    con = _seed(tmp_path)
    con.execute(
        "INSERT INTO raw_financial_ratio (symbol, year, quarter, period_type, "
        "loaded_at) VALUES ('AAA', 2025, 1, 'quarter', now())"
    )
    mig.step_rename(con)   # backup: AAA (1 dòng), bảng mới: rỗng

    con.execute(
        "INSERT INTO raw_financial_ratio (symbol, year, quarter, period_type, "
        "loaded_at) VALUES ('BBB', 2025, 1, 'quarter', now()), "
        "('CCC', 2025, 1, 'quarter', now())"
    )
    capsys.readouterr()   # xoá output của step_rename lần 1

    mig.step_rename(con)   # lần 2: bỏ qua vì backup đã tồn tại
    out = capsys.readouterr().out
    con.close()

    assert "(1 dòng)" in out          # backup (BACKUP) có 1 dòng
    assert "hiện có 2 dòng" in out    # raw_financial_ratio hiện có 2 dòng
    assert "đã tồn tại" in out
