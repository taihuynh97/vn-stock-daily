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


# I4 (fix round cuối, trả nợ test parked từ Task 2): min_composite phải lọc
# trên TOÀN VŨ TRỤ mã hợp lệ của profile, không phải trên top `limit` đã bị
# screen_report() cắt sẵn bên trong. Universe bluechip_dividend của fixture
# chỉ có đúng 2 mã đạt điều kiện (AAA composite=76, VCB composite=72.25 —
# CCC/DDD bị loại vì UPCOM); dùng ngưỡng thấp để cả 2 cùng đạt, xác nhận số
# kết quả đúng bằng min(limit, số_mã_đạt_ngưỡng), không bị cắt sai vì limit
# nhỏ được áp trước khi lọc.
def test_search_stocks_min_composite_returns_min_limit_and_qualifying_count(con):
    # limit=1 nhưng có 2 mã đạt ngưỡng thấp → chỉ trả 1 (đúng limit), và
    # phải là mã xếp hạng cao nhất (AAA), không phải bị cắt sai thứ tự.
    res = tools.search_stocks(con, profile="bluechip_dividend", limit=1, min_composite=1)
    assert len(res["results"]) == 1
    assert res["results"][0]["symbol"] == "AAA"

    # limit=5 (thừa so với số mã đạt ngưỡng) → trả đúng cả 2 mã đạt, không
    # thiếu — đây chính là ca mà lỗi cũ (lọc sau khi head(limit) BÊN TRONG
    # screen_report với limit gốc) có thể làm lộ, nếu limit gốc nhỏ hơn số
    # mã thật sự đạt ngưỡng.
    res5 = tools.search_stocks(con, profile="bluechip_dividend", limit=5, min_composite=1)
    symbols = [r["symbol"] for r in res5["results"]]
    assert symbols == ["AAA", "VCB"]


def test_search_stocks_min_composite_excludes_below_threshold(con):
    """Ngưỡng nằm giữa composite của AAA (76) và VCB (72,25) — chỉ AAA đạt."""
    res = tools.search_stocks(con, profile="bluechip_dividend", limit=10, min_composite=75)
    symbols = [r["symbol"] for r in res["results"]]
    assert symbols == ["AAA"]


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


def test_get_valuation_history_returns_series(con):
    res = tools.get_valuation_history(con, "AAA", years=5)
    assert res["symbol"] == "AAA"
    assert len(res["history"]) == 2
    latest = res["history"][0]
    assert latest["valuation_band"] == "rất rẻ"
    assert latest["pe_pct_own_5y"] == 0.18
    assert "ratio_as_of" in res


def test_get_financial_history_returns_quarters(con):
    res = tools.get_financial_history(con, "AAA", quarters=12)
    assert res["symbol"] == "AAA"
    assert len(res["history"]) == 2
    assert res["history"][0]["revenue_ttm"] == 1e13
    assert res["note"].startswith("Doanh thu và lợi nhuận là chỉ tiêu SUY RA")


def test_compare_stocks_warns_on_mixed_com_class(con):
    res = tools.compare_stocks(con, ["AAA", "VCB"])
    assert len(res["stocks"]) == 2
    assert res["comparable"] is False
    # Brief gốc viết test literal thường ("không tương đương") nhưng chính
    # code mẫu Step 3 của brief lại dựng cảnh báo với "KHÔNG" viết hoa để
    # nhấn mạnh — đúng quy ước đã có sẵn trong file này (vd note của
    # search_stocks: "KHÔNG cộng lại thành tổng"). Sửa test theo đúng quy
    # ước/hành vi thật thay vì hạ hoa cảnh báo xuống để né test.
    assert "KHÔNG tương đương" in res["warning"]


def test_compare_stocks_same_class_is_comparable(con):
    res = tools.compare_stocks(con, ["AAA", "CCC"])
    assert res["comparable"] is True
    assert res["warning"] == ""


def test_compare_stocks_reports_missing_symbol(con):
    res = tools.compare_stocks(con, ["AAA", "ZZZ"])
    assert res["not_found"] == ["ZZZ"]


# M1 (fix round cuối): compare_stocks lấy data_quality_score nhưng thiếu
# quality_flags — luật #5 của instructions.md yêu cầu "khi data_quality_score
# < 60, nêu rõ... và nêu quality_flags", nhưng compare_stocks không thể tuân
# thủ nếu thiếu cột này, đúng tool dễ chạm ngưỡng nhất (hay so sánh mã nhỏ).
def test_compare_stocks_includes_quality_flags(con):
    res = tools.compare_stocks(con, ["AAA", "CCC"])
    assert all("quality_flags" in s for s in res["stocks"])
    ccc = next(s for s in res["stocks"] if s["symbol"] == "CCC")
    assert "thiếu lịch sử" in ccc["quality_flags"]


def test_get_sector_snapshot_filters_com_class(con):
    res = tools.get_sector_snapshot(con, com_class="BANK")
    assert len(res["sectors"]) == 1
    assert res["sectors"][0]["industry_lv2"] == "Ngân hàng"
    assert res["sectors"][0]["median_pe"] == 8.6


# I2 (fix round cuối): mart_sector_snapshot có sẵn n_pe/n_pb/n_roe (đếm số
# mã CÓ dữ liệu dùng được cho từng chỉ tiêu, khác n_symbols — tổng số mã
# trong nhóm) nhưng get_sector_snapshot() từng bỏ sót cả ba khi SELECT.
# Không có 3 cột này, agent dễ hiểu nhầm median_pe của một nhóm 40 mã là
# dựa trên đủ 40 mã, trong khi thực tế production đo được 17/21 nhóm lệch.
def test_get_sector_snapshot_includes_data_coverage_counts(con):
    res = tools.get_sector_snapshot(con, com_class="NONFIN")
    sector = res["sectors"][0]
    assert "n_pe" in sector and "n_pb" in sector and "n_roe" in sector
    # Fixture cố tình đặt n_pe (32) < n_symbols (40) để mô phỏng đúng ca
    # thật — thiếu 3 cột này sẽ không lộ ra được sự lệch này.
    assert sector["n_symbols"] == 40
    assert sector["n_pe"] == 32
    assert sector["n_pe"] < sector["n_symbols"]


# Fix round 1 (code review): get_valuation_history/get_financial_history
# thiếu trường data_quality — Global Constraint của kế hoạch A3 yêu cầu MỌI
# tool trả kèm as_of và data_quality. Khoá lại hành vi sau khi vá, cùng
# pattern với test_get_stock_profile_has_quality_and_as_of đã có.
def test_get_valuation_history_includes_data_quality(con):
    res = tools.get_valuation_history(con, "AAA", years=5)
    assert "data_quality" in res
    assert res["data_quality"]["data_quality_score"] == 90
    assert res["data_quality"]["reliable"] is True


def test_get_financial_history_includes_data_quality(con):
    res = tools.get_financial_history(con, "AAA", quarters=12)
    assert "data_quality" in res
    assert res["data_quality"]["data_quality_score"] == 90
    assert res["data_quality"]["reliable"] is True
