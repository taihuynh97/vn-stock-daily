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


def _mock_finance_ratio():
    return pd.DataFrame([
        {"yearreport": "2023", "pe": 10.0, "pb": 1.5,
         "roe": 0.15, "roa": 0.08, "eps": 2000.0},
        {"yearreport": "2022", "pe": 9.5,  "pb": 1.4,
         "roe": 0.14, "roa": 0.07, "eps": 1800.0},
    ])


def test_fetch_financials_returns_expected_schema():
    with patch("src.ingest_market.Finance") as MockFin, \
         patch("src.ingest_market.ingest._throttle"):
        MockFin.return_value.ratio.return_value = _mock_finance_ratio()
        result = fetch_financials(["AAA"])
    assert set(result.columns) >= {"symbol", "period", "period_type", "pe", "pb", "roe"}
    assert result.iloc[0]["symbol"] == "AAA"
    assert result.iloc[0]["period_type"] == "year"


def test_fetch_financials_multiple_periods():
    with patch("src.ingest_market.Finance") as MockFin, \
         patch("src.ingest_market.ingest._throttle"):
        MockFin.return_value.ratio.return_value = _mock_finance_ratio()
        result = fetch_financials(["AAA"])
    assert len(result) == 2
    assert set(result["period"].tolist()) == {"2023", "2022"}


def test_fetch_financials_empty_on_exception():
    with patch("src.ingest_market.Finance") as MockFin, \
         patch("src.ingest_market.ingest._throttle"):
        MockFin.return_value.ratio.side_effect = Exception("API error")
        result = fetch_financials(["AAA"])
    assert result.empty


def test_fetch_financials_empty_on_empty_response():
    with patch("src.ingest_market.Finance") as MockFin, \
         patch("src.ingest_market.ingest._throttle"):
        MockFin.return_value.ratio.return_value = pd.DataFrame()
        result = fetch_financials(["AAA"])
    assert result.empty


def test_fetch_financials_skips_failed_symbol_continues():
    def side_effect_factory(symbol, source, period):
        mock = MagicMock()
        if symbol == "BAD":
            mock.ratio.side_effect = Exception("fail")
        else:
            mock.ratio.return_value = _mock_finance_ratio()
        return mock

    with patch("src.ingest_market.Finance", side_effect=side_effect_factory), \
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
