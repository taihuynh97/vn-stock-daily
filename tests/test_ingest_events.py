"""Test chuẩn hoá Company.events() -> schema raw_corporate_event, và test
wrapper fetch_corporate_events (mock Company(...).events(), theo đúng
pattern của tests/test_ingest_financials.py — fetch_financials/
fetch_company_info)."""
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock

from src import dq
from src.ingest_market import _normalize_events, fetch_corporate_events
import src.ingest_market as im
from src.warehouse import EVENT_COLS


@pytest.fixture(autouse=True)
def reset_event_state():
    im._printed_event_cols = False
    yield
    im._printed_event_cols = False


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


# --- Test wrapper fetch_corporate_events (mock Company(...).events()) ---
# Finding review round 1: _normalize_events (hàm chuẩn hoá thuần) đã có 6 test
# ở trên, nhưng fetch_corporate_events — vòng lặp bắt dq.SchemaError theo
# từng mã, raise lại nếu vượt ngưỡng dq.status_for, và drop_duplicates("id")
# chống trùng nội bộ mẻ — thì chưa. Đây là lệch convention thật của chính
# file này: fetch_financials/fetch_company_info (cùng src/ingest_market.py)
# đều có bộ test mock riêng cho các nhánh tương đương của wrapper. 3 test
# dưới đây theo đúng pattern side_effect_factory của
# tests/test_ingest_financials.py (test_fetch_company_info_one_bad_symbol_
# among_many_is_skipped_not_raised, test_fetch_company_info_majority_bad_
# symbols_raises).


def test_fetch_corporate_events_mot_ma_loi_giua_nhieu_ma_tot_bi_bo_qua():
    """Một mã dị thường (thiếu cả 3 cột bắt buộc id/event_code/event_title_vi)
    giữa 20 mã tốt -> 1/21 ~ 4.76% < ngưỡng degraded 5% -> mã đó bị bỏ qua
    (KHÔNG raise), 20 mã còn lại vẫn trả về đầy đủ. Cùng kịch bản Critical đã
    xác minh cho fetch_company_info/fetch_financials: một mã lẻ lỗi trong
    ~1.600 mã không được phép xoá sổ cả job đang chạy (~28 phút fetch)."""
    good_symbols = [f"S{i:03d}" for i in range(1, 21)]

    def side_effect_factory(symbol, source):
        mock = MagicMock()
        if symbol == "BAD":
            mock.events.return_value = pd.DataFrame([{"category": "DIVIDEND"}])
        else:
            mock.events.return_value = _raw_df(id=f"{symbol}-1")
        return mock

    with patch("src.ingest_market.Company", side_effect=side_effect_factory), \
         patch("src.ingest_market.ingest._throttle"):
        result = fetch_corporate_events(["BAD"] + good_symbols)
    assert len(result) == 20
    assert "BAD" not in set(result["symbol"])
    assert set(result["symbol"]) == set(good_symbols)


def test_fetch_corporate_events_da_so_ma_loi_raise():
    """Đa số mã (3/4 = 75%) sai schema -> nguồn có thể đã đổi -> raise to,
    KHÔNG âm thầm trả về 1 mã tốt còn lại."""
    def side_effect_factory(symbol, source):
        mock = MagicMock()
        if symbol == "GOOD":
            mock.events.return_value = _raw_df(id="good-1")
        else:
            mock.events.return_value = pd.DataFrame([{"category": "DIVIDEND"}])
        return mock

    with patch("src.ingest_market.Company", side_effect=side_effect_factory), \
         patch("src.ingest_market.ingest._throttle"):
        with pytest.raises(dq.SchemaError) as exc:
            fetch_corporate_events(["BAD1", "BAD2", "BAD3", "GOOD"])
    assert "3/4" in str(exc.value)


def test_fetch_corporate_events_khu_trung_id_noi_bo_me():
    """Company.events() có thể trả về 2 dòng cùng id trong một lần gọi (dữ
    liệu nguồn trùng lặp), hoặc 2 mã khác nhau vô tình chia sẻ chung một
    event_id — id là VARCHAR PRIMARY KEY ở raw_corporate_event nên trùng nội
    bộ MỘT mẻ fetch sẽ ném ConstraintException giết cả job khi
    insert_corporate_events ghi xuống (NOT EXISTS ở tầng ghi chỉ chống trùng
    với dòng ĐÃ CÓ trong bảng, không chống trùng trong cùng một mẻ).
    fetch_corporate_events phải tự khử trùng theo id trước khi trả về."""
    dup = pd.concat(
        [_raw_df(id="dup-1"), _raw_df(id="dup-1", event_title_vi="Bản lặp")],
        ignore_index=True,
    )

    with patch("src.ingest_market.Company") as MockCo, \
         patch("src.ingest_market.ingest._throttle"):
        MockCo.return_value.events.return_value = dup
        result = fetch_corporate_events(["AAA"])
    assert len(result) == 1
    assert result.iloc[0]["id"] == "dup-1"
