import duckdb
import pandas as pd
import pytest
from unittest.mock import patch

from src import dq, warehouse as wh
from src.ingest_market import fetch_industries_icb


def _mock_icb():
    """Cột thật của Listing.industries_icb() — xác minh ngày 2026-08-09."""
    return pd.DataFrame([
        {"icb_name": "Dầu khí", "en_icb_name": "Oil & Gas",
         "icb_code": "0001", "level": 1},
        {"icb_name": "Sản xuất Dầu khí", "en_icb_name": "Oil & Gas Producers",
         "icb_code": "0530", "level": 3},
        {"icb_name": "Tổ hợp Dầu khí", "en_icb_name": "Integrated Oil & Gas",
         "icb_code": "0537", "level": 4},
    ])


def test_fetch_industries_icb_schema():
    with patch("src.ingest_market.Listing") as MockL, \
         patch("src.ingest_market.ingest._throttle"):
        MockL.return_value.industries_icb.return_value = _mock_icb()
        df = fetch_industries_icb()
    assert list(df.columns) == ["icb_code", "icb_name", "en_icb_name", "level"]
    assert len(df) == 3
    assert df.iloc[0]["icb_name"] == "Dầu khí"     # giữ tiếng Việt
    assert df.iloc[0]["level"] == 1


def test_fetch_industries_icb_raises_on_missing_column():
    bad = pd.DataFrame([{"icb_name": "X", "level": 1}])
    with patch("src.ingest_market.Listing") as MockL, \
         patch("src.ingest_market.ingest._throttle"):
        MockL.return_value.industries_icb.return_value = bad
        with pytest.raises(dq.SchemaError) as exc:
            fetch_industries_icb()
    assert "icb_code" in str(exc.value)


def test_fetch_industries_icb_handles_missing_en_icb_name():
    """Nguồn không luôn trả en_icb_name (cột optional) — phải trả None thay
    vì KeyError, không rớt mất các cột còn lại."""
    no_en = pd.DataFrame([
        {"icb_name": "Dầu khí", "icb_code": "0001", "level": 1},
    ])
    with patch("src.ingest_market.Listing") as MockL, \
         patch("src.ingest_market.ingest._throttle"):
        MockL.return_value.industries_icb.return_value = no_en
        df = fetch_industries_icb()
    assert df.iloc[0]["en_icb_name"] is None
    assert df.iloc[0]["icb_code"] == "0001"


def test_fetch_industries_icb_handles_unparseable_level():
    """level không parse được số (vd. chuỗi rác) -> NaN/NA, không raise."""
    bad_level = pd.DataFrame([
        {"icb_name": "Dầu khí", "en_icb_name": "Oil & Gas",
         "icb_code": "0001", "level": "abc"},
    ])
    with patch("src.ingest_market.Listing") as MockL, \
         patch("src.ingest_market.ingest._throttle"):
        MockL.return_value.industries_icb.return_value = bad_level
        df = fetch_industries_icb()
    assert pd.isna(df.iloc[0]["level"])


def test_fetch_industries_icb_drops_duplicate_icb_code():
    """icb_code trùng lặp -> chỉ giữ dòng đầu tiên (drop_duplicates)."""
    dup = pd.DataFrame([
        {"icb_name": "Dầu khí", "en_icb_name": "Oil & Gas",
         "icb_code": "0001", "level": 1},
        {"icb_name": "Dầu khí (trùng)", "en_icb_name": "Oil & Gas dup",
         "icb_code": "0001", "level": 1},
    ])
    with patch("src.ingest_market.Listing") as MockL, \
         patch("src.ingest_market.ingest._throttle"):
        MockL.return_value.industries_icb.return_value = dup
        df = fetch_industries_icb()
    assert len(df) == 1
    assert df.iloc[0]["icb_name"] == "Dầu khí"


def test_fetch_industries_icb_empty_on_api_error():
    with patch("src.ingest_market.Listing") as MockL, \
         patch("src.ingest_market.ingest._throttle"):
        MockL.return_value.industries_icb.side_effect = Exception("down")
        df = fetch_industries_icb()
    assert df.empty


def test_upsert_industries_is_idempotent(tmp_path):
    con = duckdb.connect(str(tmp_path / "ind.duckdb"))
    wh.init_warehouse(con)
    with patch("src.ingest_market.Listing") as MockL, \
         patch("src.ingest_market.ingest._throttle"):
        MockL.return_value.industries_icb.return_value = _mock_icb()
        df = fetch_industries_icb()
    assert wh.upsert_industries(con, df) == 3
    assert wh.upsert_industries(con, df) == 3          # chạy lại
    total = con.execute("SELECT count(*) FROM dim_industry").fetchone()[0]
    name = con.execute(
        "SELECT icb_name FROM dim_industry WHERE icb_code='0537'"
    ).fetchone()[0]
    con.close()
    assert total == 3                                   # không nhân đôi
    assert name == "Tổ hợp Dầu khí"
