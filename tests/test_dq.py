import duckdb
import pandas as pd
import pytest

from src import dq, warehouse


def test_assert_columns_passes_when_all_present():
    df = pd.DataFrame({"a": [1], "b": [2]})
    dq.assert_columns(df, ["a", "b"], "nguon_test")  # không raise


def test_assert_columns_raises_and_names_missing_and_actual():
    df = pd.DataFrame({"a": [1]})
    with pytest.raises(dq.SchemaError) as exc:
        dq.assert_columns(df, ["a", "b", "c"], "nguon_test")
    msg = str(exc.value)
    assert "nguon_test" in msg
    assert "'b'" in msg and "'c'" in msg
    assert "'a'" in msg  # có in ra cột thật để debug


def test_filter_range_drops_out_of_range_keeps_nulls():
    df = pd.DataFrame({"close": [50.0, 20000.0, None, 9_999_999.0]})
    kept, rejected = dq.filter_range(df, "close", 100, 5_000_000)
    assert rejected == 2                    # 50 và 9.999.999 bị loại
    assert len(kept) == 2                   # 20000 và None được giữ
    assert kept["close"].isna().sum() == 1


def test_filter_range_missing_column_is_noop():
    df = pd.DataFrame({"a": [1]})
    kept, rejected = dq.filter_range(df, "khong_ton_tai", 0, 1)
    assert rejected == 0
    assert len(kept) == 1


def test_filter_range_empty_df_is_noop():
    kept, rejected = dq.filter_range(pd.DataFrame(), "close", 0, 1)
    assert rejected == 0
    assert kept.empty


def test_status_for_ok_degraded_empty():
    assert dq.status_for(100, 0) == "ok"
    assert dq.status_for(100, 4) == "ok"        # 3,8% <= 5%
    assert dq.status_for(100, 10) == "degraded" # 9,1% > 5%
    assert dq.status_for(0, 0) == "empty"


def test_log_load_records_rows_rejected(tmp_path):
    con = duckdb.connect(str(tmp_path / "t.duckdb"))
    warehouse.init_warehouse(con)
    warehouse.log_load(con, "job_x", "raw_price_daily", 90, "degraded",
                       watermark="2026-08-07", notes="thu", rows_rejected=10)
    row = con.execute(
        "SELECT job_name, rows_loaded, status, rows_rejected FROM etl_load_log"
    ).fetchone()
    con.close()
    assert row == ("job_x", 90, "degraded", 10)


def test_init_warehouse_is_rerunnable_and_adds_column(tmp_path):
    db = str(tmp_path / "t2.duckdb")
    con = duckdb.connect(db)
    warehouse.init_warehouse(con)
    warehouse.init_warehouse(con)   # chạy lần 2 không được lỗi
    cols = {
        r[0]
        for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'etl_load_log'"
        ).fetchall()
    }
    con.close()
    assert "rows_rejected" in cols


def test_ensure_columns_adds_missing_only_and_is_idempotent(tmp_path):
    con = duckdb.connect(str(tmp_path / "t3.duckdb"))
    con.execute("CREATE TABLE t (a INTEGER)")
    added_first = warehouse._ensure_columns(con, "t", {"a": "INTEGER", "b": "DOUBLE", "c": "VARCHAR"})
    added_second = warehouse._ensure_columns(con, "t", {"a": "INTEGER", "b": "DOUBLE", "c": "VARCHAR"})
    cols = {
        r[0]
        for r in con.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 't'"
        ).fetchall()
    }
    con.close()
    assert added_first == 2      # chỉ b và c là cột mới, a đã có sẵn
    assert added_second == 0     # chạy lại không thêm gì nữa
    assert cols == {"a", "b", "c"}
