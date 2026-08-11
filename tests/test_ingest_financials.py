import pandas as pd
import pytest
from unittest.mock import patch, MagicMock

from src import dq
from src.ingest_market import fetch_financials
import src.ingest_market as im


@pytest.fixture(autouse=True)
def reset_module_state():
    im._printed_fin_cols = False
    yield
    im._printed_fin_cols = False


def _mock_ratio_summary():
    """Company(...).ratio_summary() — quarter=5/RATIO_YEAR là tổng năm,
    quarter=1-4/RATIO_TTM là TTM kết thúc tại quý đó."""
    return pd.DataFrame([
        {"symbol": "AAA", "year": 2024, "quarter": 5, "ratio_type": "RATIO_YEAR",
         "market_cap": 1.0e13, "pe": 10.0, "pb": 1.5, "ps": 1.2,
         "dividend_yield": 0.03, "roe": 0.15, "roa": 0.08, "roic": 0.12,
         "debt_to_equity": 0.5, "current_ratio": 1.8, "gross_margin": 0.2,
         "ebit_margin": 0.18, "after_tax_profit_margin": 0.15},
        {"symbol": "AAA", "year": 2025, "quarter": 1, "ratio_type": "RATIO_TTM",
         "market_cap": 1.1e13, "pe": 11.0, "pb": 1.6, "ps": 1.3,
         "dividend_yield": 0.025, "roe": 0.16, "roa": 0.085, "roic": 0.125,
         "debt_to_equity": 0.52, "current_ratio": 1.7, "gross_margin": 0.21,
         "ebit_margin": 0.185, "after_tax_profit_margin": 0.155},
    ])


def test_fetch_financials_returns_expected_schema():
    with patch("src.ingest_market.Company") as MockCo, \
         patch("src.ingest_market.ingest._throttle"):
        MockCo.return_value.ratio_summary.return_value = _mock_ratio_summary()
        result = fetch_financials(["AAA"])
    assert set(result.columns) >= {
        "symbol", "year", "quarter", "period_type",
        "market_cap", "pe", "pb", "roe", "roa", "roic", "debt_to_equity",
    }
    assert result.iloc[0]["symbol"] == "AAA"
    year_row = result[result["quarter"] == 5].iloc[0]
    quarter_row = result[result["quarter"] == 1].iloc[0]
    assert year_row["period_type"] == "year"
    assert quarter_row["period_type"] == "quarter"


def test_fetch_financials_multiple_periods():
    with patch("src.ingest_market.Company") as MockCo, \
         patch("src.ingest_market.ingest._throttle"):
        MockCo.return_value.ratio_summary.return_value = _mock_ratio_summary()
        result = fetch_financials(["AAA"])
    assert len(result) == 2
    assert set(result["year"].tolist()) == {2024, 2025}


def test_fetch_financials_empty_on_exception():
    with patch("src.ingest_market.Company") as MockCo, \
         patch("src.ingest_market.ingest._throttle"):
        MockCo.return_value.ratio_summary.side_effect = Exception("API error")
        result = fetch_financials(["AAA"])
    assert result.empty


def test_fetch_financials_empty_on_empty_response():
    with patch("src.ingest_market.Company") as MockCo, \
         patch("src.ingest_market.ingest._throttle"):
        MockCo.return_value.ratio_summary.return_value = pd.DataFrame()
        result = fetch_financials(["AAA"])
    assert result.empty


def test_fetch_financials_skips_failed_symbol_continues():
    def side_effect_factory(symbol, source):
        mock = MagicMock()
        if symbol == "BAD":
            mock.ratio_summary.side_effect = Exception("fail")
        else:
            mock.ratio_summary.return_value = _mock_ratio_summary()
        return mock

    with patch("src.ingest_market.Company", side_effect=side_effect_factory), \
         patch("src.ingest_market.ingest._throttle"):
        result = fetch_financials(["BAD", "AAA"])
    assert len(result) > 0
    assert all(result["symbol"] == "AAA")


from src.ingest_market import fetch_company_info


@pytest.fixture(autouse=True)
def reset_info_state():
    im._printed_info_cols = False
    im._warned_unknown_exchange = False
    yield
    im._printed_info_cols = False
    im._warned_unknown_exchange = False


from src import warehouse as wh


def _mock_company_overview():
    """Cột thật của Company.overview() — xác minh bằng HPG ngày 2026-08-09.

    com_group_code = "VNINDEX" (giá trị API thật trả cho HPG, KHÔNG phải
    "HOSE" trực tiếp — xem _COM_GROUP_TO_EXCHANGE). Dùng đúng giá trị thô
    này để test cấp cao đi qua đường ánh xạ thật của _map_exchange, không
    chỉ đi qua nhánh identity fallthrough."""
    return pd.DataFrame([{
        "symbol": "HPG",
        "organ_name": "Công ty Cổ phần Tập đoàn Hòa Phát",
        "organ_short_name": "Hòa Phát",
        "com_group_code": "VNINDEX",
        "com_type_code": "CT",
        "is_bank": False,
        "icb_code_lv2": "1700",
        "icb_code_lv4": "1757",
        "sector": "Basic Resources",
        "market_cap": 1.4e14,
        "issue_share": 7.7e9,
        "free_float_percentage": 0.55,
        "foreigner_percentage": 0.22,
        "maximum_foreign_percentage": 0.49,
        "state_percentage": 0.0,
        "average_match_value1_month": 3.0e11,
        "average_match_volume1_month": 1.3e7,
        "highest_price1_year": 29000.0,
        "lowest_price1_year": 19500.0,
        "listing_date": "2007-11-15",
    }])


def test_fetch_company_info_maps_real_columns():
    with patch("src.ingest_market.Company") as MockCo, \
         patch("src.ingest_market.ingest._throttle"):
        MockCo.return_value.overview.return_value = _mock_company_overview()
        result = fetch_company_info(["HPG"])
    row = result.iloc[0]
    assert row["symbol"] == "HPG"
    assert row["exchange"] == "HOSE"           # com_group_code="VNINDEX" -> map thật -> HOSE
    assert row["icb_code_lv2"] == "1700"       # từ icb_code_lv2, KHÔNG phải NULL
    assert row["icb_code_lv4"] == "1757"
    assert row["com_type_code"] == "CT"
    assert bool(row["is_bank"]) is False
    assert row["free_float_percentage"] == pytest.approx(0.55)
    assert row["avg_match_value_1m"] == pytest.approx(3.0e11)
    assert str(row["listed_date"]) == "2007-11-15"


def test_fetch_company_info_bank_flag_true():
    df = _mock_company_overview()
    df.loc[0, "symbol"] = "VCB"
    df.loc[0, "is_bank"] = True
    df.loc[0, "sector"] = "Banks"
    with patch("src.ingest_market.Company") as MockCo, \
         patch("src.ingest_market.ingest._throttle"):
        MockCo.return_value.overview.return_value = df
        result = fetch_company_info(["VCB"])
    assert bool(result.iloc[0]["is_bank"]) is True


def test_fetch_company_info_returns_all_company_cols():
    with patch("src.ingest_market.Company") as MockCo, \
         patch("src.ingest_market.ingest._throttle"):
        MockCo.return_value.overview.return_value = _mock_company_overview()
        result = fetch_company_info(["HPG"])
    assert list(result.columns) == wh.COMPANY_COLS


def test_fetch_company_info_skips_failed_continues():
    """Một mã lỗi (API raise) thì bị bỏ qua, các mã còn lại vẫn được trả về —
    hành vi mất assertion trực tiếp sau khi test cũ bị xoá ở Task 3."""
    def side_effect_factory(symbol, source):
        mock = MagicMock()
        if symbol == "BAD":
            mock.overview.side_effect = Exception("API down")
        else:
            df = _mock_company_overview()
            df.loc[0, "symbol"] = symbol
            mock.overview.return_value = df
        return mock

    with patch("src.ingest_market.Company", side_effect=side_effect_factory), \
         patch("src.ingest_market.ingest._throttle"):
        result = fetch_company_info(["BAD", "HPG"])
    assert len(result) == 1
    assert result.iloc[0]["symbol"] == "HPG"


def test_fetch_company_info_missing_symbol_column_raises():
    """1/1 mã sai schema = 100% > ngưỡng degraded (5%) -> raise. Thông báo giờ
    là thông báo TỔNG HỢP (tỉ lệ mã lỗi), không còn lặp lại chi tiết cột thiếu
    của một mã cụ thể — xem C2/finding review cuối: một mã lỗi bị bắt và đếm
    riêng, chỉ raise (to, tổng hợp) khi tỉ lệ vượt ngưỡng."""
    bad = pd.DataFrame([{"organ_name": "X"}])
    with patch("src.ingest_market.Company") as MockCo, \
         patch("src.ingest_market.ingest._throttle"):
        MockCo.return_value.overview.return_value = bad
        with pytest.raises(dq.SchemaError) as exc:
            fetch_company_info(["HPG"])
    assert "1/1" in str(exc.value)
    assert "sai schema" in str(exc.value)


def test_fetch_company_info_one_bad_symbol_among_many_is_skipped_not_raised():
    """Một mã dị thường (thiếu cột bắt buộc) giữa 20 mã tốt -> 1/21 ~ 4.76% <
    ngưỡng degraded 5% -> mã đó bị bỏ qua (KHÔNG raise), 20 mã còn lại vẫn trả
    về đầy đủ. Đây là kịch bản Critical đã được xác minh: trước bản sửa này,
    một mã lẻ lỗi làm mất trắng cả job monthly (~28 phút fetch)."""
    good_symbols = [f"S{i:03d}" for i in range(1, 21)]

    def side_effect_factory(symbol, source):
        mock = MagicMock()
        if symbol == "BAD":
            mock.overview.return_value = pd.DataFrame([{"organ_name": "X"}])
        else:
            df = _mock_company_overview()
            df.loc[0, "symbol"] = symbol
            mock.overview.return_value = df
        return mock

    with patch("src.ingest_market.Company", side_effect=side_effect_factory), \
         patch("src.ingest_market.ingest._throttle"):
        result = fetch_company_info(["BAD"] + good_symbols)
    assert len(result) == 20
    assert "BAD" not in set(result["symbol"])
    assert set(result["symbol"]) == set(good_symbols)


def test_fetch_company_info_majority_bad_symbols_raises():
    """Đa số mã (3/4 = 75%) sai schema -> nguồn có thể đã đổi -> raise to,
    KHÔNG âm thầm trả về 1 mã tốt còn lại."""
    def side_effect_factory(symbol, source):
        mock = MagicMock()
        if symbol == "GOOD":
            df = _mock_company_overview()
            df.loc[0, "symbol"] = symbol
            mock.overview.return_value = df
        else:
            mock.overview.return_value = pd.DataFrame([{"organ_name": "X"}])
        return mock

    with patch("src.ingest_market.Company", side_effect=side_effect_factory), \
         patch("src.ingest_market.ingest._throttle"):
        with pytest.raises(dq.SchemaError) as exc:
            fetch_company_info(["BAD1", "BAD2", "BAD3", "GOOD"])
    assert "3/4" in str(exc.value)


def test_fetch_company_info_empty_on_exception():
    with patch("src.ingest_market.Company") as MockCo, \
         patch("src.ingest_market.ingest._throttle"):
        MockCo.return_value.overview.side_effect = Exception("API down")
        result = fetch_company_info(["HPG"])
    assert result.empty


def test_map_exchange_maps_otc_to_otc_not_none():
    """com_group_code == 'OTC' — xác minh bằng controller dò toàn bộ 219 mã
    exchange NULL trên production (2026-08-10): 185/219 là 'OTC'. Đây là một
    nơi giao dịch hợp lệ, riêng biệt (phi tập trung, ngoài 3 sàn niêm yết) —
    map thành 'OTC' trung thực hơn None, và không được coi là giá trị lạ
    (không được kích hoạt cảnh báo _warned_unknown_exchange)."""
    assert im._map_exchange("OTC") == "OTC"
    assert im._map_exchange("otc") == "OTC"   # không phân biệt hoa/thường


def test_map_exchange_translates_real_api_index_names():
    """Giá trị thô thật mà Company.overview() trả cho com_group_code — xác
    minh trực tiếp với API cho HPG/VCB/VNM/BSR (HOSE), IDV/VNR/SHS (HNX),
    PHP/MLS (UPCOM)."""
    assert im._map_exchange("VNINDEX") == "HOSE"
    assert im._map_exchange("HNXIndex") == "HNX"
    assert im._map_exchange("UpcomIndex") == "UPCOM"


def test_map_exchange_unknown_value_returns_none_not_raw_string():
    """Giá trị lạ (sàn mới, mã huỷ niêm yết,...) phải trả None, KHÔNG phải
    chuỗi thô — chuỗi lạ ghi thẳng vào raw_company_info.exchange sẽ giả dạng
    dữ liệu hợp lệ trong khi thực ra không xác định được sàn."""
    assert im._map_exchange("SomeNewIndex") is None


def test_map_exchange_unknown_value_warns_once(capsys):
    """Cảnh báo cho giá trị lạ chỉ in MỘT LẦN (debounce qua _warned_unknown_exchange,
    được reset ở fixture reset_info_state) và nội dung nêu đúng giá trị lạ đầu
    tiên gặp phải, không lặp lại cho giá trị lạ thứ hai."""
    assert im._map_exchange("WeirdExchangeA") is None
    assert im._map_exchange("WeirdExchangeB") is None
    out = capsys.readouterr().out
    warning_lines = [ln for ln in out.splitlines() if "com_group_code lạ" in ln]
    assert len(warning_lines) == 1
    assert "WEIRDEXCHANGEA" in warning_lines[0]
    assert "WEIRDEXCHANGEB" not in warning_lines[0]


def test_update_symbol_exchanges_fills_dim_symbols(tmp_path):
    import duckdb
    con = duckdb.connect(str(tmp_path / "ci.duckdb"))
    wh.init_warehouse(con)
    con.execute(
        "INSERT INTO dim_symbols (symbol, exchange, company_name, is_active, "
        "first_seen, last_seen) VALUES ('HPG', NULL, 'HP', TRUE, "
        "DATE '2026-01-01', DATE '2026-08-07')"
    )
    with patch("src.ingest_market.Company") as MockCo, \
         patch("src.ingest_market.ingest._throttle"):
        MockCo.return_value.overview.return_value = _mock_company_overview()
        info = fetch_company_info(["HPG"])
    wh.upsert_company_info(con, info)
    n = wh.update_symbol_exchanges(con)
    got = con.execute("SELECT exchange FROM dim_symbols WHERE symbol='HPG'").fetchone()[0]
    con.close()
    assert n == 1
    assert got == "HOSE"


def _mock_bank_ratio_summary():
    """VCB: cột ngân hàng có giá trị, cột phi tài chính là sentinel 0.0."""
    return pd.DataFrame([{
        "symbol": "VCB", "year": 2026, "quarter": 2, "ratio_type": "RATIO_TTM",
        "market_cap": 5.0e14, "number_of_shares_mkt_cap": 5.5e9,
        "dividend_yield": 0.008, "pe": 15.2, "pb": 2.6, "ps": 5.1,
        "roe": 0.19, "roa": 0.017, "debt_to_equity": 9.8,
        "gross_margin": 0.68, "pre_tax_profit_margin": 0.41,
        "after_tax_profit_margin": 0.33,
        # phi tài chính — sentinel 0.0 do VCI trả
        "roic": 0.0, "current_ratio": 0.0, "ebit_margin": 0.0,
        "quick_ratio": 0.0, "cash_ratio": 0.0, "asset_turnover": 0.0,
        "ev_to_ebitda": 0.0, "price_to_cash_flow": 2.2,
        "fixed_asset_turnover": 0.0, "cash_cycle": 0.0,
        "day_sale_outstanding": 0.0, "days_inventory_outstanding": 0.0,
        "days_payable_outstanding": 0.0, "ebit": 0.0, "ebitda": 0.0,
        "debt_per_equity": 0.0,
        # ngân hàng — giá trị thật
        "net_interest_margin": 0.025, "average_yield_on_earning_assets": 0.053,
        "average_cost_of_financing": -0.029, "non_and_interest_income": 0.33,
        "cir": -0.41, "loans_growth": 0.049, "deposit_growth": 0.046,
        "equity_to_liabilities": 0.064, "equity_to_loans": 0.097,
        "total_equity_total_asset": 0.060, "ldr_loan_deposit_ratio": 0.79,
        "npl": 0.0115, "loans_loss_reserve_to_loans": 0.016,
        "provision_to_outstanding_loans": -0.011, "car": 0.12,
        "casa_ratio": 0.35,
    }])


def test_ratio_column_constants_have_expected_sizes():
    assert len(wh.RATIO_COMMON) == 13
    assert len(wh.RATIO_NONFIN) == 15
    assert len(wh.RATIO_BANK) == 16
    assert len(wh.RATIO_NUM_COLS) == 44
    assert len(wh.RATIO_ALL_COLS) == 49
    # không được trùng cột giữa các nhóm
    assert len(set(wh.RATIO_NUM_COLS)) == 44
    # hai cột trùng lặp đã xác minh phải bị loại
    assert "financial_leverage" not in wh.RATIO_NUM_COLS
    assert "cost_to_income" not in wh.RATIO_NUM_COLS
    # cột đòn bẩy thứ hai (khác debt_to_equity) phải được giữ
    assert "debt_per_equity" in wh.RATIO_NONFIN


def test_fetch_financials_keeps_bank_metrics():
    with patch("src.ingest_market.Company") as MockCo, \
         patch("src.ingest_market.ingest._throttle"):
        MockCo.return_value.ratio_summary.return_value = _mock_bank_ratio_summary()
        result = fetch_financials(["VCB"])
    row = result.iloc[0]
    assert row["net_interest_margin"] == pytest.approx(0.025)
    assert row["npl"] == pytest.approx(0.0115)
    assert row["cir"] == pytest.approx(-0.41)     # giữ nguyên dấu ở raw
    assert row["casa_ratio"] == pytest.approx(0.35)
    assert row["number_of_shares_mkt_cap"] == pytest.approx(5.5e9)
    assert row["ratio_type"] == "RATIO_TTM"


def test_fetch_financials_returns_all_ratio_columns():
    with patch("src.ingest_market.Company") as MockCo, \
         patch("src.ingest_market.ingest._throttle"):
        MockCo.return_value.ratio_summary.return_value = _mock_bank_ratio_summary()
        result = fetch_financials(["VCB"])
    assert list(result.columns) == wh.RATIO_ALL_COLS


def test_fetch_financials_missing_year_column_raises():
    """1/1 mã sai schema = 100% > ngưỡng degraded (5%) -> raise. Thông báo giờ
    là thông báo TỔNG HỢP (tỉ lệ mã lỗi) — xem C2/finding review cuối."""
    bad = pd.DataFrame([{"symbol": "AAA", "quarter": 1, "pe": 10.0}])
    with patch("src.ingest_market.Company") as MockCo, \
         patch("src.ingest_market.ingest._throttle"):
        MockCo.return_value.ratio_summary.return_value = bad
        with pytest.raises(dq.SchemaError) as exc:
            fetch_financials(["AAA"])
    assert "1/1" in str(exc.value)
    assert "sai schema" in str(exc.value)


def test_fetch_financials_one_bad_symbol_among_many_is_skipped_not_raised():
    """Một mã dị thường giữa 20 mã tốt -> 1/21 ~ 4.76% < ngưỡng degraded 5%
    -> mã đó bị bỏ qua (KHÔNG raise), 20 mã còn lại vẫn trả về đầy đủ."""
    good_symbols = [f"S{i:03d}" for i in range(1, 21)]

    def side_effect_factory(symbol, source):
        mock = MagicMock()
        if symbol == "BAD":
            mock.ratio_summary.return_value = pd.DataFrame(
                [{"symbol": "BAD", "quarter": 1, "pe": 10.0}]
            )
        else:
            df = _mock_ratio_summary()
            df["symbol"] = symbol
            mock.ratio_summary.return_value = df
        return mock

    with patch("src.ingest_market.Company", side_effect=side_effect_factory), \
         patch("src.ingest_market.ingest._throttle"):
        result = fetch_financials(["BAD"] + good_symbols)
    assert "BAD" not in set(result["symbol"])
    assert set(result["symbol"]) == set(good_symbols)


def test_fetch_financials_majority_bad_symbols_raises():
    """Đa số mã (3/4 = 75%) sai schema -> raise to, KHÔNG âm thầm trả về 1 mã
    tốt còn lại."""
    def side_effect_factory(symbol, source):
        mock = MagicMock()
        if symbol == "GOOD":
            df = _mock_ratio_summary()
            df["symbol"] = symbol
            mock.ratio_summary.return_value = df
        else:
            mock.ratio_summary.return_value = pd.DataFrame(
                [{"symbol": symbol, "quarter": 1, "pe": 10.0}]
            )
        return mock

    with patch("src.ingest_market.Company", side_effect=side_effect_factory), \
         patch("src.ingest_market.ingest._throttle"):
        with pytest.raises(dq.SchemaError) as exc:
            fetch_financials(["BAD1", "BAD2", "BAD3", "GOOD"])
    assert "3/4" in str(exc.value)


def test_upsert_financial_ratios_roundtrip(tmp_path):
    import duckdb
    con = duckdb.connect(str(tmp_path / "fin.duckdb"))
    wh.init_warehouse(con)
    with patch("src.ingest_market.Company") as MockCo, \
         patch("src.ingest_market.ingest._throttle"):
        MockCo.return_value.ratio_summary.return_value = _mock_bank_ratio_summary()
        df = fetch_financials(["VCB"])
    n = wh.upsert_financial_ratios(con, df)
    stored = con.execute(
        "SELECT symbol, npl, car, loaded_at IS NOT NULL "
        "FROM raw_financial_ratio"
    ).fetchone()
    con.close()
    assert n == 1
    assert stored[0] == "VCB"
    assert stored[1] == pytest.approx(0.0115)
    assert stored[2] == pytest.approx(0.12)
    assert stored[3] is True
