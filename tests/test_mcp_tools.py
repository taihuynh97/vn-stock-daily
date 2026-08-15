import duckdb
import pytest

from mcp_server import tools
from tests.conftest_mart import build_fake_mart


@pytest.fixture
def con(tmp_path):
    path = str(tmp_path / "mart.duckdb")
    build_fake_mart(path)
    c = duckdb.connect(path, read_only=True)
    yield c
    c.close()


def test_search_stocks_returns_ranked_with_as_of(con):
    res = tools.search_stocks(con, profile="bluechip_dividend", limit=10)
    assert res["profile"] == "bluechip_dividend"
    assert "price_as_of" in res and "ratio_as_of" in res
    symbols = [r["symbol"] for r in res["results"]]
    assert "CCC" not in symbols            # UPCOM + thanh khoản thấp → loại
    assert res["universe_size"] >= 1
    assert "rejected_counts" in res and "rejected_total" in res


def test_search_stocks_includes_peer_basis_and_facts(con):
    res = tools.search_stocks(con, profile="bluechip_dividend", limit=10)
    first = res["results"][0]
    assert "peer_basis" in first and "peer_count" in first
    assert "composite_score" in first
    assert "facts" in first


def test_get_stock_profile_has_quality_and_as_of(con):
    res = tools.get_stock_profile(con, "AAA")
    assert res["symbol"] == "AAA"
    assert res["com_class"] == "NONFIN"
    assert res["scores"]["quality"] == 70
    assert res["data_quality"]["data_quality_score"] == 90
    assert res["price_as_of"] == "2026-08-07"


def test_get_stock_profile_warns_on_low_quality(con):
    res = tools.get_stock_profile(con, "CCC")
    assert res["data_quality"]["data_quality_score"] == 45
    assert res["data_quality"]["reliable"] is False
    assert "thiếu lịch sử" in res["data_quality"]["quality_flags"]


def test_get_stock_profile_unknown_symbol(con):
    res = tools.get_stock_profile(con, "ZZZ")
    assert "error" in res
    assert "ZZZ" in res["error"]


def test_get_stock_profile_null_dates_return_none_not_nat(con):
    """Fix round 1 (code review): DDD có ratio_as_of NULL thật (mã mới niêm
    yết, chưa có kỳ định giá nào) và không có dòng khớp trong dim_stock nên
    listed_date cũng NULL qua LEFT JOIN. `_date_str()` từng trả chuỗi literal
    "NaT" cho các ca này (pandas.NaT lọt qua guard `isinstance(v, float)`,
    vì NaT không phải kiểu float) — phải trả None."""
    res = tools.get_stock_profile(con, "DDD")
    assert res["ratio_as_of"] is None
    assert res["listed_date"] is None
    assert res["ratio_as_of"] != "NaT"
    assert res["listed_date"] != "NaT"
    # price_as_of của DDD có giá trị thật — xác nhận ca không-NULL vẫn đúng
    # định dạng "YYYY-MM-DD" như trước, sửa guard không làm hỏng đường này.
    assert res["price_as_of"] == "2026-08-07"
