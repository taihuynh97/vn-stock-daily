"""Test unpivot wide -> dài cho BCTC (income_statement/balance_sheet/cash_flow)."""
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock

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


def _good_report_df() -> pd.DataFrame:
    return pd.DataFrame({
        "item":    ["Doanh thu thuần"],
        "item_en": ["Net sales"],
        "item_id": ["net_sales"],
        "2026-Q2": [100.0],
    })


def _report_thieu_item_en() -> pd.DataFrame:
    """Mô phỏng đúng bug Finding 1 (review Task 2): report thiếu hẳn cột
    item_en. Trước bản sửa, _STATEMENT_REQUIRED = ["item_id", "item"] không
    có "item_en" nên dq.assert_columns không bắt được thiếu cột này —
    df.melt(id_vars=[..., "item_en", ...]) ở _unpivot_statement ném KeyError
    TRẦN (không phải dq.SchemaError), lọt qua khối except dq.SchemaError bọc
    quanh trong fetch_financial_statements và làm sập cả hàm."""
    return pd.DataFrame({
        "item":    ["Doanh thu thuần"],
        "item_id": ["net_sales"],
        "2026-Q2": [100.0],
    })


def test_fetch_financial_statements_mot_bao_cao_loi_giua_nhieu_bao_cao_tot_bi_bo_qua():
    """Một (mã, statement_type) dị thường (DataFrame thiếu item_en) giữa
    nhiều report tốt khác (kể cả 2 statement_type còn lại của CHÍNH mã đó)
    -> KHÔNG được làm sập cả hàm (Global Constraints: một báo cáo dị thường
    không được xoá sổ cả mẻ ~1.600 mã). Report lỗi bị bỏ qua, mọi report tốt
    khác (bao gồm 2 statement_type còn lại của mã BAD) vẫn có trong kết quả.

    Trước khi sửa Finding 1: test này THẤT BẠI vì KeyError ('item_en') ném
    trần từ df.melt(), không bị dq.SchemaError bắt -> văng thẳng ra khỏi
    fetch_financial_statements."""
    good_symbols = [f"S{i:03d}" for i in range(1, 21)]

    def side_effect_factory(symbol, source, period):
        mock = MagicMock()
        if symbol == "BAD":
            mock.income_statement.return_value = _report_thieu_item_en()
            mock.balance_sheet.return_value = _good_report_df()
            mock.cash_flow.return_value = _good_report_df()
        else:
            mock.income_statement.return_value = _good_report_df()
            mock.balance_sheet.return_value = _good_report_df()
            mock.cash_flow.return_value = _good_report_df()
        return mock

    with patch("src.ingest_market.Finance", side_effect=side_effect_factory), \
         patch("src.ingest_market.ingest._throttle"):
        result = fetch_financial_statements(["BAD"] + good_symbols)

    bad_income = result[(result["symbol"] == "BAD") & (result["statement_type"] == "income_statement")]
    bad_other = result[(result["symbol"] == "BAD") & (result["statement_type"] != "income_statement")]
    assert bad_income.empty  # report lỗi bị bỏ qua
    assert set(bad_other["statement_type"]) == {"balance_sheet", "cash_flow"}  # 2 report tốt còn lại của BAD vẫn còn
    assert set(result[result["symbol"] != "BAD"]["symbol"]) == set(good_symbols)
