from unittest.mock import patch

import duckdb
import pandas as pd

from src import warehouse as wh
from scripts import reconcile_warehouse as rw


def _seed(tmp_path):
    con = duckdb.connect(str(tmp_path / "rec.duckdb"))
    wh.init_warehouse(con)
    con.execute(
        "INSERT INTO dim_symbols (symbol, exchange, company_name, is_active, "
        "first_seen, last_seen) VALUES "
        "('AAA','HOSE','A',TRUE,DATE '2026-01-01',DATE '2026-08-07'),"
        "('BBB','HNX','B',TRUE,DATE '2026-01-01',DATE '2026-08-07')"
    )
    con.execute(
        "INSERT INTO raw_price_daily (symbol, trade_date, open, high, low, "
        "close, volume, value, loaded_at) VALUES "
        "('AAA',DATE '2026-08-07',1,1,1,20000,1000,20.0,now())"
    )
    return con


def test_check_layer_counts_flags_missing_prices(tmp_path):
    con = _seed(tmp_path)
    rows = rw.check_layer_counts(con)
    con.close()
    by_name = {r["check"]: r for r in rows}
    assert by_name["dim_symbols"]["value"] == 2
    assert by_name["raw_price_daily_symbols"]["value"] == 1
    assert by_name["raw_price_daily_symbols"]["ok"] is False   # 1/2 = 50% < 95%


def test_check_layer_counts_passes_when_complete(tmp_path):
    con = _seed(tmp_path)
    con.execute(
        "INSERT INTO raw_price_daily (symbol, trade_date, open, high, low, "
        "close, volume, value, loaded_at) VALUES "
        "('BBB',DATE '2026-08-07',1,1,1,15000,900,15.0,now())"
    )
    rows = rw.check_layer_counts(con)
    con.close()
    by_name = {r["check"]: r for r in rows}
    assert by_name["raw_price_daily_symbols"]["ok"] is True


def test_check_layer_counts_returns_expected_checks(tmp_path):
    con = _seed(tmp_path)
    names = {r["check"] for r in rw.check_layer_counts(con)}
    con.close()
    assert {"dim_symbols", "raw_price_daily_symbols",
            "raw_company_info_symbols", "raw_financial_ratio_symbols",
            "dim_industry_rows", "raw_index_daily_codes",
            "symbols_missing_ratio", "index_close_in_range",
            "banks_with_metrics"} <= names


def test_check_layer_counts_symbols_missing_ratio_fails_when_over_tolerance(tmp_path):
    con = _seed(tmp_path)
    # AAA và BBB đều active nhưng chưa mã nào có tỷ số -> 100% thiếu > 5%.
    rows = rw.check_layer_counts(con)
    con.close()
    by_name = {r["check"]: r for r in rows}
    assert by_name["symbols_missing_ratio"]["value"] == 2
    assert by_name["symbols_missing_ratio"]["ok"] is False


def test_check_layer_counts_symbols_missing_ratio_ok_when_covered(tmp_path):
    con = _seed(tmp_path)
    _seed_ratio(con, "AAA", 2025, 1, roe=0.15, roa=0.08)
    _seed_ratio(con, "BBB", 2025, 1, roe=0.15, roa=0.08)
    rows = rw.check_layer_counts(con)
    con.close()
    by_name = {r["check"]: r for r in rows}
    assert by_name["symbols_missing_ratio"]["value"] == 0
    assert by_name["symbols_missing_ratio"]["ok"] is True


# --- I7: raw_company_info_symbols phải là count(DISTINCT symbol) GIAO active,
# KHÔNG count(*) đơn thuần trên một bảng chỉ tăng ---

def test_check_layer_counts_raw_company_info_counts_distinct_active_symbols_only(tmp_path):
    """Kịch bản Critical mà count(*) che giấu: raw_company_info có dữ liệu
    cho các mã KHÔNG active (đã hủy niêm yết, dữ liệu vẫn còn vì bảng chỉ
    tăng, không xoá) nhưng KHÔNG có cho mã đang active. count(*) đơn thuần
    sẽ đếm cả các mã không active đó vào coverage, khiến check có thể ĐẠT
    trong khi thực tế các mã đang hoạt động thiếu hồ sơ hoàn toàn."""
    con = _seed(tmp_path)   # AAA, BBB active
    # Thêm 3 mã đã hủy niêm yết (KHÔNG active) và nạp raw_company_info cho
    # từng mã đó -- count(*) sẽ đếm ra 3, "trông có vẻ" gần đạt 95% của 2 mã
    # active (total*0.95 = 1.9), nhưng thực tế KHÔNG mã active nào có hồ sơ.
    for i, sym in enumerate(["OLD1", "OLD2", "OLD3"]):
        con.execute(
            "INSERT INTO dim_symbols (symbol, exchange, company_name, "
            "is_active, first_seen, last_seen) VALUES "
            "(?, 'HOSE', ?, FALSE, DATE '2015-01-01', DATE '2020-01-01')",
            [sym, sym],
        )
        con.execute(
            "INSERT INTO raw_company_info (symbol, company_name, loaded_at) "
            "VALUES (?, ?, now())",
            [sym, sym],
        )
    rows = rw.check_layer_counts(con)
    con.close()
    by_name = {r["check"]: r for r in rows}
    # Đúng: 0 mã ACTIVE có hồ sơ -> value phải là 0, KHÔNG phải 3.
    assert by_name["raw_company_info_symbols"]["value"] == 0
    assert by_name["raw_company_info_symbols"]["ok"] is False


def test_check_layer_counts_raw_company_info_ok_when_active_symbols_covered(tmp_path):
    con = _seed(tmp_path)   # AAA, BBB active
    con.execute(
        "INSERT INTO raw_company_info (symbol, company_name, loaded_at) VALUES "
        "('AAA', 'A', now()), ('BBB', 'B', now())"
    )
    rows = rw.check_layer_counts(con)
    con.close()
    by_name = {r["check"]: r for r in rows}
    assert by_name["raw_company_info_symbols"]["value"] == 2
    assert by_name["raw_company_info_symbols"]["ok"] is True


# --- I7: index_close_in_range — hàng phòng thủ tự động chống lỗi đơn vị x1000 ---

def test_check_layer_counts_index_close_in_range_ok_when_no_data(tmp_path):
    """Chưa có dữ liệu VNINDEX -> không tính là fail ở CHECK NÀY (đã được
    canh riêng bởi raw_index_daily_codes)."""
    con = _seed(tmp_path)
    rows = rw.check_layer_counts(con)
    con.close()
    by_name = {r["check"]: r for r in rows}
    assert by_name["index_close_in_range"]["value"] is None
    assert by_name["index_close_in_range"]["ok"] is True


def test_check_layer_counts_index_close_in_range_ok_for_real_value(tmp_path):
    con = _seed(tmp_path)
    con.execute(
        "INSERT INTO raw_index_daily (index_code, trade_date, open, high, low, "
        "close, volume, loaded_at) VALUES "
        "('VNINDEX', DATE '2026-08-07', 1760, 1770, 1750, 1768.06, 500000000, now())"
    )
    rows = rw.check_layer_counts(con)
    con.close()
    by_name = {r["check"]: r for r in rows}
    assert by_name["index_close_in_range"]["ok"] is True


def test_check_layer_counts_index_close_in_range_fails_on_x1000_regression(tmp_path):
    """Đúng lớp lỗi mà fetch_index_history được viết riêng (không nhân 1000)
    để phòng — nếu regression tái xuất hiện (vd. ai đó lỡ tái dùng
    fetch_history_one cho chỉ số), max(close) VNINDEX sẽ nhảy lên hàng triệu
    và check này PHẢI bắt được."""
    con = _seed(tmp_path)
    con.execute(
        "INSERT INTO raw_index_daily (index_code, trade_date, open, high, low, "
        "close, volume, loaded_at) VALUES "
        "('VNINDEX', DATE '2026-08-07', 1760000, 1770000, 1750000, 1768060, "
        "500000000, now())"
    )
    rows = rw.check_layer_counts(con)
    con.close()
    by_name = {r["check"]: r for r in rows}
    assert by_name["index_close_in_range"]["value"] == 1768060
    assert by_name["index_close_in_range"]["ok"] is False


# --- I7: banks_with_metrics — bao nhiêu NH có đủ chỉ tiêu cốt lõi ở kỳ mới nhất ---

def _seed_bank(con, symbol, year, quarter, nim=0.02, npl=0.01, cir=-0.4):
    con.execute(
        "INSERT INTO raw_company_info (symbol, company_name, is_bank, loaded_at) "
        "VALUES (?, ?, TRUE, now())",
        [symbol, symbol],
    )
    con.execute(
        "INSERT INTO raw_financial_ratio (symbol, year, quarter, period_type, "
        "net_interest_margin, npl, cir, loaded_at) VALUES "
        "(?, ?, ?, 'quarter', ?, ?, ?, now())",
        [symbol, year, quarter, nim, npl, cir],
    )


def test_check_layer_counts_banks_with_metrics_ok_when_at_least_25(tmp_path):
    con = _seed(tmp_path)
    for i in range(25):
        _seed_bank(con, f"B{i:03d}", 2026, 2)
    rows = rw.check_layer_counts(con)
    con.close()
    by_name = {r["check"]: r for r in rows}
    assert by_name["banks_with_metrics"]["value"] == 25
    assert by_name["banks_with_metrics"]["ok"] is True


def test_check_layer_counts_banks_with_metrics_fails_when_under_25(tmp_path):
    con = _seed(tmp_path)
    for i in range(24):
        _seed_bank(con, f"B{i:03d}", 2026, 2)
    rows = rw.check_layer_counts(con)
    con.close()
    by_name = {r["check"]: r for r in rows}
    assert by_name["banks_with_metrics"]["value"] == 24
    assert by_name["banks_with_metrics"]["ok"] is False


def test_check_layer_counts_banks_with_metrics_only_counts_latest_period(tmp_path):
    """Ngân hàng có kỳ CŨ đủ 3 chỉ tiêu nhưng kỳ MỚI NHẤT thiếu (vd. cir NULL)
    -> KHÔNG được tính, vì check phải phản ánh tình trạng hiện tại."""
    con = _seed(tmp_path)
    for i in range(25):
        _seed_bank(con, f"B{i:03d}", 2026, 1)   # 25 mã, kỳ cũ đủ 3 chỉ tiêu
    # Một trong số đó (B000) có kỳ MỚI HƠN (2026Q2) nhưng thiếu cir.
    con.execute(
        "INSERT INTO raw_financial_ratio (symbol, year, quarter, period_type, "
        "net_interest_margin, npl, cir, loaded_at) VALUES "
        "('B000', 2026, 2, 'quarter', 0.02, 0.01, NULL, now())"
    )
    rows = rw.check_layer_counts(con)
    con.close()
    by_name = {r["check"]: r for r in rows}
    # B000 bị loại vì kỳ mới nhất (2026Q2) thiếu cir -> còn 24 mã đủ điều kiện.
    assert by_name["banks_with_metrics"]["value"] == 24


def _seed_ratio(con, symbol, year, quarter, roe=None, roa=None, pe=None):
    con.execute(
        "INSERT INTO raw_financial_ratio (symbol, year, quarter, period_type, "
        "pe, roe, roa, loaded_at) VALUES (?, ?, ?, 'quarter', ?, ?, ?, now())",
        [symbol, year, quarter, pe, roe, roa],
    )


def test_check_against_source_same_period_flags_real_drift(tmp_path):
    con = _seed(tmp_path)
    _seed_ratio(con, "AAA", 2025, 1, roe=0.15, roa=0.08)
    api_df = pd.DataFrame([{"year": 2025, "quarter": 1, "roe": 0.60, "roa": 0.08}])
    with patch("src.ingest_market.fetch_financials", return_value=api_df):
        rows = rw.check_against_source(con, ["AAA"])
    con.close()
    assert rows[0]["ok"] is False   # cùng kỳ, roe lệch 4x -> phải fail


def test_check_against_source_pe_drift_ignored_roe_roa_match_is_ok(tmp_path):
    """C4 (review cuối, xác minh trên production): pe/pb/ps/market_cap đều tỷ
    lệ với market_cap, mà market_cap API tính từ giá THỜI ĐIỂM GỌI API — lệch
    với warehouse (nạp hôm trước) không phải sai lệch DỮ LIỆU. Chạy thật:
    4/5 mã lệch cùng kỳ 1.27%-7.41% vì lý do này, roe/roa lệch đúng 0.00%.
    So pe sẽ làm reconcile_warehouse (chạy trong workflow monthly, sys.exit(1))
    đỏ gần như mọi lần chạy. Test này khẳng định: pe lệch RẤT LỚN nhưng
    roe/roa khớp -> ok=True. Nếu ai đó "cải tiến" bằng cách thêm pe trở lại
    vào phép so, test này sẽ đỏ."""
    con = _seed(tmp_path)
    _seed_ratio(con, "AAA", 2025, 1, roe=0.15, roa=0.08)
    api_df = pd.DataFrame([{
        "year": 2025, "quarter": 1,
        "pe": 999.0,     # lệch cực lớn so với warehouse (không lưu, không so)
        "roe": 0.15, "roa": 0.08,   # khớp warehouse
    }])
    with patch("src.ingest_market.fetch_financials", return_value=api_df):
        rows = rw.check_against_source(con, ["AAA"])
    con.close()
    assert rows[0]["ok"] is True
    assert rw._COMPARE_COLS == ["roe", "roa"]   # pe/pb/ps/market_cap không được có mặt


def test_check_against_source_same_period_within_tolerance_passes(tmp_path):
    con = _seed(tmp_path)
    _seed_ratio(con, "AAA", 2025, 1, roe=0.15, roa=0.08)
    api_df = pd.DataFrame([{"year": 2025, "quarter": 1, "roe": 0.15, "roa": 0.08}])
    with patch("src.ingest_market.fetch_financials", return_value=api_df):
        rows = rw.check_against_source(con, ["AAA"])
    con.close()
    assert rows[0]["ok"] is True
    assert "2025Q1" in rows[0]["detail"]


def test_check_against_source_newer_api_period_is_informational_not_fail(tmp_path):
    con = _seed(tmp_path)
    _seed_ratio(con, "AAA", 2025, 1, roe=0.15, roa=0.08)
    # API đã công bố kỳ mới hơn (2025Q2) mà warehouse chưa kịp reload — API
    # KHÔNG có 2025Q1 nên không thể so kỳ. Giá trị 2025Q2 lệch rất lớn so với
    # warehouse nhưng đây không phải lỗi dữ liệu, chỉ là chưa reload kỳ mới.
    api_df = pd.DataFrame([{"year": 2025, "quarter": 2, "roe": 0.99, "roa": 0.99}])
    with patch("src.ingest_market.fetch_financials", return_value=api_df):
        rows = rw.check_against_source(con, ["AAA"])
    con.close()
    assert rows[0]["ok"] is True
    assert "2025Q1" in rows[0]["detail"] and "2025Q2" in rows[0]["detail"]


def test_check_against_source_api_empty_is_not_fail(tmp_path):
    con = _seed(tmp_path)
    _seed_ratio(con, "AAA", 2025, 1, roe=0.15, roa=0.08)
    with patch("src.ingest_market.fetch_financials", return_value=pd.DataFrame()):
        rows = rw.check_against_source(con, ["AAA"])
    con.close()
    assert rows[0]["ok"] is True


def test_check_against_source_symbol_with_no_ratio_row_is_informational_not_fail(tmp_path):
    """Mã được lấy mẫu chưa có dòng nào trong raw_financial_ratio (~13/1598
    mã thực tế) không được tính là fail — độ phủ đã được canh có hệ thống ở
    check_layer_counts (symbols_missing_ratio), không phải qua mẫu 5 mã ngẫu
    nhiên của check_against_source (tránh CI đỏ ngẫu nhiên)."""
    con = _seed(tmp_path)
    # AAA active nhưng KHÔNG seed dòng nào trong raw_financial_ratio.
    rows = rw.check_against_source(con, ["AAA"])
    con.close()
    assert rows[0]["ok"] is True
    assert "AAA" in rows[0]["detail"]
