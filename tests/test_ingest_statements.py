"""Test unpivot wide -> dài cho BCTC (income_statement/balance_sheet/cash_flow)."""
import pandas as pd
import pytest

from src import dq
from src.ingest_market import _unpivot_statement, fetch_financial_statements
from src.warehouse import STATEMENT_COLS


def _wide_df(**kw) -> pd.DataFrame:
    """Dựng DataFrame giống nguyên trạng nguồn trả về — 3 cột item + N cột
    kỳ. Mặc định mô phỏng đúng ca thật: 'cost' xuất hiện 2 lần (2 nhóm tài
    sản khác nhau, cùng item_id, khác item/item_en) để test row_seq phân
    biệt được, cộng 1 dòng bình thường."""
    df = pd.DataFrame({
        "item":    ["Doanh thu thuần", "Nguyên giá TSCĐ hữu hình", "Nguyên giá tài sản đầu tư"],
        "item_en": ["Net sales", "Cost of tangible fixed assets", "Cost of investment property"],
        "item_id": ["net_sales", "cost", "cost"],
        "2026-Q2": [100.0, 10.0, 5.0],
        "2026-Q1": [90.0, 9.0, 4.0],
    })
    return df


def test_unpivot_tra_dung_bo_cot():
    out = _unpivot_statement(_wide_df(), "HPG", "balance_sheet", "quarter")
    assert list(out.columns) == STATEMENT_COLS


def test_unpivot_moi_dong_x_moi_ky_thanh_mot_dong_dai():
    out = _unpivot_statement(_wide_df(), "HPG", "balance_sheet", "quarter")
    # 3 dòng gốc x 2 cột kỳ = 6 dòng dài
    assert len(out) == 6


def test_unpivot_giu_dung_row_seq_phan_biet_hai_dong_trung_item_id():
    out = _unpivot_statement(_wide_df(), "HPG", "balance_sheet", "quarter")
    cost_rows = out[out["item_id"] == "cost"]
    assert set(cost_rows["row_seq"]) == {1, 2}
    r1 = cost_rows[cost_rows["row_seq"] == 1].iloc[0]
    r2 = cost_rows[cost_rows["row_seq"] == 2].iloc[0]
    assert r1["item_vi"] == "Nguyên giá TSCĐ hữu hình"
    assert r2["item_vi"] == "Nguyên giá tài sản đầu tư"


def test_unpivot_symbol_ep_hoa_va_statement_type_period_type_dung():
    out = _unpivot_statement(_wide_df(), "hpg", "balance_sheet", "quarter")
    assert (out["symbol"] == "HPG").all()
    assert (out["statement_type"] == "balance_sheet").all()
    assert (out["period_type"] == "quarter").all()


def test_unpivot_gia_tri_giu_dung_so():
    out = _unpivot_statement(_wide_df(), "HPG", "balance_sheet", "quarter")
    row = out[(out["item_id"] == "net_sales") & (out["period_label"] == "2026-Q2")]
    assert row.iloc[0]["value"] == pytest.approx(100.0)


def test_unpivot_df_rong_tra_df_rong_dung_cot():
    out = _unpivot_statement(pd.DataFrame(), "HPG", "balance_sheet", "quarter")
    assert list(out.columns) == STATEMENT_COLS
    assert len(out) == 0


def test_unpivot_df_none_tra_df_rong():
    out = _unpivot_statement(None, "HPG", "balance_sheet", "quarter")
    assert len(out) == 0
