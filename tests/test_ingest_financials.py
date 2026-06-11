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
