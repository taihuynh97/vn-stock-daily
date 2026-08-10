import pandas as pd
import pytest
from unittest.mock import patch, MagicMock

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
    yield
    im._printed_info_cols = False


def _mock_company_overview():
    return pd.DataFrame([{
        "organ_name": "An Phat Bioplastics",
        "exchange": "HOSE",
        "industry_icb_name2": "Industrials",
        "sector": "Chemicals",
        "listing_date": "2010-01-15",
    }])


def test_fetch_company_info_returns_expected_schema():
    with patch("src.ingest_market.Company") as MockCo, \
         patch("src.ingest_market.ingest._throttle"):
        MockCo.return_value.overview.return_value = _mock_company_overview()
        result = fetch_company_info(["AAA"])
    assert set(result.columns) >= {"symbol", "company_name", "exchange", "industry_icb"}
    assert result.iloc[0]["symbol"] == "AAA"


def test_fetch_company_info_empty_on_exception():
    with patch("src.ingest_market.Company") as MockCo, \
         patch("src.ingest_market.ingest._throttle"):
        MockCo.return_value.overview.side_effect = Exception("API down")
        result = fetch_company_info(["AAA"])
    assert result.empty


def test_fetch_company_info_skips_failed_continues():
    call_count = [0]
    def factory(symbol, source):
        mock = MagicMock()
        call_count[0] += 1
        if call_count[0] == 1:
            mock.overview.side_effect = Exception("fail")
        else:
            mock.overview.return_value = _mock_company_overview()
        return mock

    with patch("src.ingest_market.Company", side_effect=factory), \
         patch("src.ingest_market.ingest._throttle"):
        result = fetch_company_info(["BAD", "AAA"])
    assert len(result) == 1
    assert result.iloc[0]["symbol"] == "AAA"


from src import warehouse as wh


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
    bad = pd.DataFrame([{"symbol": "AAA", "quarter": 1, "pe": 10.0}])
    with patch("src.ingest_market.Company") as MockCo, \
         patch("src.ingest_market.ingest._throttle"):
        MockCo.return_value.ratio_summary.return_value = bad
        with pytest.raises(Exception) as exc:
            fetch_financials(["AAA"])
    assert "year" in str(exc.value)


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
