"""Test cho scripts/migrate_financial_ratio_v2.py — tập trung vào logic phá
hủy (rename/cleanup) sắp chạy lên production 10 năm dữ liệu.

Chỉ test step_rename/step_verify/step_cleanup (thuần SQL trên DuckDB tạm,
không gọi API). Không test step_reload vì nó cần API thật.
"""
import duckdb
import pytest

from src import warehouse as wh
from scripts import migrate_financial_ratio_v2 as mig


def _seed(tmp_path):
    con = duckdb.connect(str(tmp_path / "mig.duckdb"))
    wh.init_warehouse(con)
    return con


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
