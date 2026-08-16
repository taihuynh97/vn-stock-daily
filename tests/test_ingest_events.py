"""Test chuẩn hoá Company.events() -> schema raw_corporate_event."""
import pandas as pd
import pytest

from src import dq
from src.ingest_market import _normalize_events
from src.warehouse import EVENT_COLS


def _raw_df(**kw) -> pd.DataFrame:
    """Dựng DataFrame giống nguyên trạng nguồn trả về (22 cột, có cả cột *_en
    mà ta cố ý không lấy)."""
    row = {
        "id": 12345, "event_name_vi": "Trả cổ tức bằng tiền mặt",
        "event_name_en": "Cash dividend", "ticker": "HPG", "event_code": "DIV",
        "event_title_vi": "Trả cổ tức bằng tiền mặt - Cả năm 2025 - 500 VND",
        "event_title_en": "Cash dividend - FY2025 - 500 VND",
        "display_date1": "2026-05-11", "display_date2": "2026-05-12",
        "public_date": "2026-04-20", "issue_date": "2026-04-20",
        "category": "DIVIDEND", "start_date": None, "end_date": None,
        "action_type_vi": None, "action_type_en": None,
        "record_date": "2026-05-12", "exright_date": "2026-05-11",
        "listing_date": None, "exercise_ratio": 0.05,
        "payout_date": "2026-06-30", "value_per_share": 500.0,
    }
    row.update(kw)
    return pd.DataFrame([row])


def test_normalize_tra_dung_bo_cot():
    out = _normalize_events(_raw_df(), "HPG")
    assert list(out.columns) == EVENT_COLS


def test_id_ep_ve_chuoi_va_symbol_lay_tu_tham_so():
    """id nguồn là số nguyên; bảng đích khai VARCHAR PRIMARY KEY nên phải ép
    chuỗi ngay ở đây, không để DuckDB tự ép ngầm. symbol lấy từ tham số chứ
    không từ cột `ticker` — cùng lý do như các hàm fetch khác trong file:
    tham số là thứ ta chủ động kiểm soát, cột nguồn có thể vắng."""
    out = _normalize_events(_raw_df(), "hpg")
    assert out.loc[0, "id"] == "12345"
    assert out.loc[0, "symbol"] == "HPG"


def test_ngay_ep_ve_chuoi_iso():
    out = _normalize_events(_raw_df(), "HPG")
    assert out.loc[0, "exright_date"] == "2026-05-11"
    assert out.loc[0, "payout_date"] == "2026-06-30"


def test_ngay_null_giu_nguyen_none_khong_thanh_chuoi_nat():
    """Bài học A3 fix round 1: pandas NaT lọt qua guard kiểu float rồi
    isoformat() ra chuỗi literal 'NaT'. Cột ngày rỗng phải là None."""
    out = _normalize_events(_raw_df(), "HPG")
    assert out.loc[0, "start_date"] is None or pd.isna(out.loc[0, "start_date"])


def test_thieu_cot_bat_buoc_raise_schema_error():
    df = _raw_df().drop(columns=["event_code"])
    with pytest.raises(dq.SchemaError):
        _normalize_events(df, "HPG")


def test_gia_tri_so_giu_dung_kieu():
    out = _normalize_events(_raw_df(), "HPG")
    assert out.loc[0, "exercise_ratio"] == pytest.approx(0.05)
    assert out.loc[0, "value_per_share"] == pytest.approx(500.0)
