# tests/test_warehouse_cleanup.py
import duckdb
from src import warehouse


def test_delete_trade_date_removes_only_matching_rows():
    con = duckdb.connect(":memory:")
    warehouse.init_warehouse(con)

    con.execute(
        """
        INSERT INTO raw_price_daily VALUES
        ('AAA', '2026-06-05', 1, 2, 3, 4, 100, 1.0, now()),
        ('AAA', '2026-06-07', 1, 2, 3, 4, 100, 1.0, now()),
        ('BBB', '2026-06-07', 1, 2, 3, 4, 100, 1.0, now())
        """
    )

    n = warehouse.delete_trade_date(con, "2026-06-07")
    assert n == 2

    remaining = con.execute(
        "SELECT symbol, trade_date::VARCHAR FROM raw_price_daily ORDER BY symbol, trade_date"
    ).fetchall()
    assert remaining == [("AAA", "2026-06-05")]


def test_delete_trade_date_returns_zero_when_nothing_matches():
    con = duckdb.connect(":memory:")
    warehouse.init_warehouse(con)

    con.execute(
        """
        INSERT INTO raw_price_daily VALUES
        ('AAA', '2026-06-05', 1, 2, 3, 4, 100, 1.0, now())
        """
    )

    n = warehouse.delete_trade_date(con, "2026-06-07")
    assert n == 0
