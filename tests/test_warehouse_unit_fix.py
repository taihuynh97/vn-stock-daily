# tests/test_warehouse_unit_fix.py
import duckdb
from src import warehouse


def test_fix_backfill_price_units_scales_only_null_value_rows():
    con = duckdb.connect(":memory:")
    warehouse.init_warehouse(con)

    con.execute(
        """
        INSERT INTO raw_price_daily VALUES
        ('AAA', '2024-01-02', 50.0, 52.0, 49.0, 51.0, 100000, NULL, now()),
        ('BBB', '2026-06-08', 61200.0, 62100.0, 60900.0, 61700.0, 7352300, 451580.18, now())
        """
    )

    n = warehouse.fix_backfill_price_units(con)
    assert n == 1

    aaa = con.execute(
        "SELECT open, high, low, close FROM raw_price_daily WHERE symbol='AAA'"
    ).fetchone()
    assert aaa == (50000.0, 52000.0, 49000.0, 51000.0)

    bbb = con.execute(
        "SELECT open, high, low, close FROM raw_price_daily WHERE symbol='BBB'"
    ).fetchone()
    assert bbb == (61200.0, 62100.0, 60900.0, 61700.0)


def test_fix_backfill_price_units_returns_zero_when_nothing_to_fix():
    con = duckdb.connect(":memory:")
    warehouse.init_warehouse(con)

    con.execute(
        """
        INSERT INTO raw_price_daily VALUES
        ('BBB', '2026-06-08', 61200.0, 62100.0, 60900.0, 61700.0, 7352300, 451580.18, now())
        """
    )

    n = warehouse.fix_backfill_price_units(con)
    assert n == 0
