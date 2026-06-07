# tests/test_warehouse_backfill.py
import duckdb
import pytest
from src import warehouse


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    warehouse.init_warehouse(c)
    warehouse.init_backfill_status(c)
    return c


def test_init_creates_table(con):
    rows = con.execute("SELECT count(*) FROM backfill_status").fetchone()[0]
    assert rows == 0


def test_get_pending_returns_symbols_not_done(con):
    con.execute("INSERT INTO dim_symbols VALUES ('AAA','HOSE','Test',TRUE,'2020-01-01','2026-01-01')")
    con.execute("INSERT INTO dim_symbols VALUES ('BBB','HNX','Test2',TRUE,'2020-01-01','2026-01-01')")
    con.execute("INSERT INTO backfill_status VALUES ('BBB','done','2026-06-01',NULL,now())")
    pending = warehouse.get_pending_symbols(con)
    assert pending == ['AAA']


def test_mark_done_updates_status(con):
    con.execute("INSERT INTO dim_symbols VALUES ('VNM','HOSE','Vinamilk',TRUE,'2020-01-01','2026-01-01')")
    warehouse.mark_backfill_done(con, 'VNM', '2026-06-07')
    row = con.execute("SELECT status, last_date FROM backfill_status WHERE symbol='VNM'").fetchone()
    assert row[0] == 'done'
    assert str(row[1]) == '2026-06-07'


def test_mark_error_sets_error_status(con):
    con.execute("INSERT INTO dim_symbols VALUES ('XYZ','HOSE','XYZ Co',TRUE,'2020-01-01','2026-01-01')")
    warehouse.mark_backfill_error(con, 'XYZ', 'timeout')
    row = con.execute("SELECT status, notes FROM backfill_status WHERE symbol='XYZ'").fetchone()
    assert row[0] == 'error'
    assert row[1] == 'timeout'


def test_mark_done_idempotent(con):
    con.execute("INSERT INTO dim_symbols VALUES ('FPT','HOSE','FPT',TRUE,'2020-01-01','2026-01-01')")
    warehouse.mark_backfill_done(con, 'FPT', '2026-06-06')
    warehouse.mark_backfill_done(con, 'FPT', '2026-06-07')
    count = con.execute("SELECT count(*) FROM backfill_status WHERE symbol='FPT'").fetchone()[0]
    assert count == 1


def test_error_to_done_clears_notes(con):
    con.execute("INSERT INTO dim_symbols VALUES ('HPG','HOSE','Hoa Phat',TRUE,'2020-01-01','2026-01-01')")
    warehouse.mark_backfill_error(con, 'HPG', 'timeout')
    warehouse.mark_backfill_done(con, 'HPG', '2026-06-07')
    row = con.execute("SELECT status, notes FROM backfill_status WHERE symbol='HPG'").fetchone()
    assert row[0] == 'done'
    assert row[1] is None
