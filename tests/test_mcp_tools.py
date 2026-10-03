import duckdb
import pytest

from mcp_server import db, tools
from tests.conftest_mart import build_fake_mart


@pytest.fixture
def con(tmp_path):
    path = str(tmp_path / "mart.duckdb")
    build_fake_mart(path)
    c = duckdb.connect(path, read_only=True)
    yield c
    c.close()


def test_search_stocks_returns_ranked_with_as_of(con):
    res = tools.search_stocks(con, profile="bluechip_dividend", limit=10)
    assert res["profile"] == "bluechip_dividend"
    assert "price_as_of" in res and "ratio_as_of" in res
    symbols = [r["symbol"] for r in res["results"]]
    assert "CCC" not in symbols            # UPCOM + thanh khoản thấp → loại
    assert res["universe_size"] >= 1
    assert "rejected_counts" in res and "rejected_total" in res


# I4 (fix round cuối, trả nợ test parked từ Task 2): min_composite phải lọc
# trên TOÀN VŨ TRỤ mã hợp lệ của profile, không phải trên top `limit` đã bị
# screen_report() cắt sẵn bên trong. Universe bluechip_dividend của fixture
# chỉ có đúng 2 mã đạt điều kiện (AAA composite=76, VCB composite=72.25 —
# CCC/DDD bị loại vì UPCOM); dùng ngưỡng thấp để cả 2 cùng đạt, xác nhận số
# kết quả đúng bằng min(limit, số_mã_đạt_ngưỡng), không bị cắt sai vì limit
# nhỏ được áp trước khi lọc.
def test_search_stocks_min_composite_returns_min_limit_and_qualifying_count(con):
    # limit=1 nhưng có 2 mã đạt ngưỡng thấp → chỉ trả 1 (đúng limit), và
    # phải là mã xếp hạng cao nhất (AAA), không phải bị cắt sai thứ tự.
    res = tools.search_stocks(con, profile="bluechip_dividend", limit=1, min_composite=1)
    assert len(res["results"]) == 1
    assert res["results"][0]["symbol"] == "AAA"

    # limit=5 (thừa so với số mã đạt ngưỡng) → trả đúng cả 2 mã đạt, không
    # thiếu — đây chính là ca mà lỗi cũ (lọc sau khi head(limit) BÊN TRONG
    # screen_report với limit gốc) có thể làm lộ, nếu limit gốc nhỏ hơn số
    # mã thật sự đạt ngưỡng.
    res5 = tools.search_stocks(con, profile="bluechip_dividend", limit=5, min_composite=1)
    symbols = [r["symbol"] for r in res5["results"]]
    assert symbols == ["AAA", "VCB"]


def test_search_stocks_min_composite_excludes_below_threshold(con):
    """Ngưỡng nằm giữa composite của AAA (76) và VCB (72,25) — chỉ AAA đạt."""
    res = tools.search_stocks(con, profile="bluechip_dividend", limit=10, min_composite=75)
    symbols = [r["symbol"] for r in res["results"]]
    assert symbols == ["AAA"]


def test_search_stocks_includes_peer_basis_and_facts(con):
    res = tools.search_stocks(con, profile="bluechip_dividend", limit=10)
    first = res["results"][0]
    assert "peer_basis" in first and "peer_count" in first
    assert "composite_score" in first
    assert "facts" in first


def test_get_stock_profile_has_quality_and_as_of(con):
    res = tools.get_stock_profile(con, "AAA")
    assert res["symbol"] == "AAA"
    assert res["com_class"] == "NONFIN"
    assert res["scores"]["quality"] == 70
    assert res["data_quality"]["data_quality_score"] == 90
    assert res["price_as_of"] == "2026-08-07"


def test_get_stock_profile_warns_on_low_quality(con):
    res = tools.get_stock_profile(con, "CCC")
    assert res["data_quality"]["data_quality_score"] == 45
    assert res["data_quality"]["reliable"] is False
    assert "thiếu lịch sử" in res["data_quality"]["quality_flags"]


def test_get_stock_profile_unknown_symbol(con):
    res = tools.get_stock_profile(con, "ZZZ")
    assert "error" in res
    assert "ZZZ" in res["error"]


def test_get_stock_profile_null_dates_return_none_not_nat(con):
    """Fix round 1 (code review): DDD có ratio_as_of NULL thật (mã mới niêm
    yết, chưa có kỳ định giá nào) và không có dòng khớp trong dim_stock nên
    listed_date cũng NULL qua LEFT JOIN. `_date_str()` từng trả chuỗi literal
    "NaT" cho các ca này (pandas.NaT lọt qua guard `isinstance(v, float)`,
    vì NaT không phải kiểu float) — phải trả None."""
    res = tools.get_stock_profile(con, "DDD")
    assert res["ratio_as_of"] is None
    assert res["listed_date"] is None
    assert res["ratio_as_of"] != "NaT"
    assert res["listed_date"] != "NaT"
    # price_as_of của DDD có giá trị thật — xác nhận ca không-NULL vẫn đúng
    # định dạng "YYYY-MM-DD" như trước, sửa guard không làm hỏng đường này.
    assert res["price_as_of"] == "2026-08-07"


def test_get_valuation_history_returns_series(con):
    res = tools.get_valuation_history(con, "AAA", years=5)
    assert res["symbol"] == "AAA"
    assert len(res["history"]) == 2
    latest = res["history"][0]
    assert latest["valuation_band"] == "rất rẻ"
    assert latest["pe_pct_own_5y"] == 0.18
    assert "ratio_as_of" in res


def test_get_financial_history_returns_quarters(con):
    res = tools.get_financial_history(con, "AAA", quarters=12)
    assert res["symbol"] == "AAA"
    assert len(res["history"]) == 2
    assert res["history"][0]["revenue_ttm"] == 1e13
    assert res["note"].startswith("Doanh thu và lợi nhuận là chỉ tiêu SUY RA")


def test_compare_stocks_warns_on_mixed_com_class(con):
    res = tools.compare_stocks(con, ["AAA", "VCB"])
    assert len(res["stocks"]) == 2
    assert res["comparable"] is False
    # Brief gốc viết test literal thường ("không tương đương") nhưng chính
    # code mẫu Step 3 của brief lại dựng cảnh báo với "KHÔNG" viết hoa để
    # nhấn mạnh — đúng quy ước đã có sẵn trong file này (vd note của
    # search_stocks: "KHÔNG cộng lại thành tổng"). Sửa test theo đúng quy
    # ước/hành vi thật thay vì hạ hoa cảnh báo xuống để né test.
    assert "KHÔNG tương đương" in res["warning"]


def test_compare_stocks_same_class_is_comparable(con):
    res = tools.compare_stocks(con, ["AAA", "CCC"])
    assert res["comparable"] is True
    assert res["warning"] == ""


def test_compare_stocks_reports_missing_symbol(con):
    res = tools.compare_stocks(con, ["AAA", "ZZZ"])
    assert res["not_found"] == ["ZZZ"]


# M1 (fix round cuối): compare_stocks lấy data_quality_score nhưng thiếu
# quality_flags — luật #5 của instructions.md yêu cầu "khi data_quality_score
# < 60, nêu rõ... và nêu quality_flags", nhưng compare_stocks không thể tuân
# thủ nếu thiếu cột này, đúng tool dễ chạm ngưỡng nhất (hay so sánh mã nhỏ).
def test_compare_stocks_includes_quality_flags(con):
    res = tools.compare_stocks(con, ["AAA", "CCC"])
    assert all("quality_flags" in s for s in res["stocks"])
    ccc = next(s for s in res["stocks"] if s["symbol"] == "CCC")
    assert "thiếu lịch sử" in ccc["quality_flags"]


def test_get_sector_snapshot_filters_com_class(con):
    res = tools.get_sector_snapshot(con, com_class="BANK")
    assert len(res["sectors"]) == 1
    assert res["sectors"][0]["industry_lv2"] == "Ngân hàng"
    assert res["sectors"][0]["median_pe"] == 8.6


# I2 (fix round cuối): mart_sector_snapshot có sẵn n_pe/n_pb/n_roe (đếm số
# mã CÓ dữ liệu dùng được cho từng chỉ tiêu, khác n_symbols — tổng số mã
# trong nhóm) nhưng get_sector_snapshot() từng bỏ sót cả ba khi SELECT.
# Không có 3 cột này, agent dễ hiểu nhầm median_pe của một nhóm 40 mã là
# dựa trên đủ 40 mã, trong khi thực tế production đo được 17/21 nhóm lệch.
def test_get_sector_snapshot_includes_data_coverage_counts(con):
    res = tools.get_sector_snapshot(con, com_class="NONFIN")
    sector = res["sectors"][0]
    assert "n_pe" in sector and "n_pb" in sector and "n_roe" in sector
    # Fixture cố tình đặt n_pe (32) < n_symbols (40) để mô phỏng đúng ca
    # thật — thiếu 3 cột này sẽ không lộ ra được sự lệch này.
    assert sector["n_symbols"] == 40
    assert sector["n_pe"] == 32
    assert sector["n_pe"] < sector["n_symbols"]


# Fix round 1 (code review): get_valuation_history/get_financial_history
# thiếu trường data_quality — Global Constraint của kế hoạch A3 yêu cầu MỌI
# tool trả kèm as_of và data_quality. Khoá lại hành vi sau khi vá, cùng
# pattern với test_get_stock_profile_has_quality_and_as_of đã có.
def test_get_valuation_history_includes_data_quality(con):
    res = tools.get_valuation_history(con, "AAA", years=5)
    assert "data_quality" in res
    assert res["data_quality"]["data_quality_score"] == 90
    assert res["data_quality"]["reliable"] is True


def test_get_financial_history_includes_data_quality(con):
    res = tools.get_financial_history(con, "AAA", quarters=12)
    assert "data_quality" in res
    assert res["data_quality"]["data_quality_score"] == 90
    assert res["data_quality"]["reliable"] is True


def test_get_distribution_history_tra_hai_khoi_tach_bach(con):
    """Hướng A của spec: KHÔNG ép ghép hai trục thời gian.

    dividend_yield gán theo NĂM TÀI CHÍNH, sự kiện gán theo NGÀY GDKHQ —
    cổ tức 'cả năm 2021' của HPG chi trả 17/06/2022. Trả hai khối riêng,
    mỗi khối ghi rõ trục của nó.
    """
    res = tools.get_distribution_history(con, "AAA", years=5)
    assert res["symbol"] == "AAA"
    assert "cash_dividend_by_fiscal_year" in res
    assert "distribution_events" in res
    assert len(res["distribution_events"]) == 3
    assert "KHÔNG cộng gộp" in res["note"]


def test_get_distribution_history_phan_biet_tien_mat_va_co_phieu(con):
    res = tools.get_distribution_history(con, "AAA", years=5)
    by_type = {e["distribution_type"]: e for e in res["distribution_events"]}
    assert by_type["CASH_DIVIDEND"]["cash_per_share"] == 500.0
    assert by_type["CASH_DIVIDEND"]["stock_ratio"] is None
    assert by_type["STOCK_DIVIDEND"]["stock_ratio"] == 0.10
    assert by_type["STOCK_DIVIDEND"]["cash_per_share"] is None


def test_get_distribution_history_phoi_do_sau_cua_so(con):
    """event_window_years là trường BẮT BUỘC — chính con số này phân biệt
    'VNM mới trả cổ tức 3 năm nay' (sai) với 'cửa sổ chỉ nhìn được 1,5 năm'
    (đúng).

    M6 (fix round cuối): pin giá trị cụ thể thay vì chỉ kiểm tồn tại trường
    — assertion cũ vẫn xanh kể cả khi giá trị là None. Fixture AAA có 3 sự
    kiện trải exright_date 2022-06-17 (e3, cũ nhất) -> 2026-05-25 (e2, mới
    nhất) = 1.438 ngày = 3,9 năm (làm tròn 1 chữ số thập phân, đúng công
    thức trong get_distribution_history)."""
    res = tools.get_distribution_history(con, "AAA", years=5)
    dq_block = res["data_quality"]
    assert dq_block["event_window_start"] == "2022-06-17"
    assert dq_block["event_window_end"] == "2026-05-25"
    assert dq_block["event_window_years"] == pytest.approx(3.9)
    assert dq_block["n_events"] == 3


def test_get_distribution_history_ngay_dung_dinh_dang_iso(con):
    """Bài học A3: cột DATE qua .df() thành Timestamp, isoformat() ra kèm
    'T00:00:00'."""
    res = tools.get_distribution_history(con, "AAA", years=5)
    assert res["distribution_events"][0]["exright_date"] == "2026-05-25"


def test_get_distribution_history_ma_khong_ton_tai(con):
    res = tools.get_distribution_history(con, "ZZZ", years=5)
    assert "error" in res
    assert "ZZZ" in res["error"]


# I4 (fix round cuối): int_distribution_event lọc `exright_date is not
# null` — hợp lý (không có trục thời gian thì không đặt lên timeline được)
# nhưng production đo được 323/9932 sự kiện (3,36%) bị loại theo cách này
# mà không có tín hiệu nào cho agent biết. EEE trong fixture có dividend_yield
# thật (nên không rơi vào nhánh lỗi "không có dữ liệu") nhưng KHÔNG có dòng
# nào trong int_distribution_event — sự kiện duy nhất của nó bị lọc mất vì
# exright_date NULL (xem stg_corporate_event trong conftest_mart.py).
def test_get_distribution_history_phoi_su_kien_thieu_exright_date(con):
    res = tools.get_distribution_history(con, "EEE", years=5)
    dq_block = res["data_quality"]
    assert dq_block["n_events"] == 0
    assert dq_block["n_events_missing_exright_date"] >= 1
    assert "KHÔNG có ngày GDKHQ" in res["note"]


def test_get_distribution_history_khong_canh_bao_khi_khong_thieu(con):
    """AAA không có sự kiện nào bị lọc mất — n_events_missing_exright_date
    phải là 0 và note KHÔNG chứa câu cảnh báo (tránh báo động giả cho mã
    dữ liệu đầy đủ)."""
    res = tools.get_distribution_history(con, "AAA", years=5)
    assert res["data_quality"]["n_events_missing_exright_date"] == 0
    assert "KHÔNG có ngày GDKHQ" not in res["note"]


def test_get_ownership_tra_co_dong_va_ban_lanh_dao(con):
    res = tools.get_ownership(con, "AAA")
    assert res["symbol"] == "AAA"
    assert len(res["major_shareholders"]) == 3
    assert res["major_shareholders"][0]["percent"] == 0.2580
    assert len(res["officers"]) == 2
    assert res["snapshot_date"] == "2026-08-01"


def test_get_ownership_phoi_tong_phan_tram_cong_bo(con):
    """total_disclosed_pct phải hiện rõ: tổng KHÔNG bằng 100%, giấu đi thì
    agent suy ra sai 'phần còn lại là free float'."""
    res = tools.get_ownership(con, "AAA")
    assert res["concentration"]["total_disclosed_pct"] == 0.5189
    assert res["concentration"]["n_disclosed"] == 66
    assert "free float" in res["note"]


# I1 (fix round cuối): int_ownership_snapshot.snapshot_date là ngày snapshot
# của CỔ ĐÔNG, insider_pct tính từ max(snapshot_date) RIÊNG của bảng
# officer. get_ownership từng dùng đúng MỘT snapshot_date để lọc cả
# stg_shareholder lẫn stg_officer — khi hai ngày lệch nhau (mã lỗi fetch ở
# lần chạy monthly này cho một trong hai nguồn), officers trả về rỗng trong
# khi insider_pct (tính đúng từ ngày khác) vẫn có số, payload tự mâu thuẫn.
# BBB trong fixture dựng đúng ca này: shareholder snapshot 2026-08-01,
# officer snapshot 2026-07-01.
def test_get_ownership_officers_dung_snapshot_rieng_khi_lech_ngay(con):
    res = tools.get_ownership(con, "BBB")
    assert res["snapshot_date"] == "2026-08-01"
    assert res["concentration"]["insider_pct"] == pytest.approx(0.15)
    # Trước fix: officers rỗng dù insider_pct có số — đúng bug reviewer tái
    # hiện. Sau fix: officers phải khớp dữ liệu thật (snapshot 2026-07-01).
    assert len(res["officers"]) == 1
    assert res["officers"][0]["name"] == "Ông D"
    assert len(res["major_shareholders"]) == 1


def test_get_ownership_ma_khong_ton_tai(con):
    res = tools.get_ownership(con, "ZZZ")
    assert "error" in res


def test_get_financial_statement_tra_dung_dang_moi_dong_kem_chuoi_ky(con):
    res = tools.get_financial_statement(con, "AAA", "income_statement")
    assert res["symbol"] == "AAA"
    assert res["statement_type"] == "income_statement"
    assert res["n_items"] == 1
    item = res["items"][0]
    assert item["item_id"] == "net_sales"
    assert item["item_vi"] == "Doanh thu thuần"
    assert item["values_by_period"]["2026-Q2"] == 100.0
    assert item["values_by_period"]["2026-Q1"] == 90.0
    # Minor finding fix round 1 (review): n_periods_available chưa có test
    # nào assert trước đây — fixture có đúng 2 kỳ (2026-Q2, 2026-Q1) cho
    # income_statement AAA.
    assert res["data_quality"]["has_data"] is True
    assert res["data_quality"]["n_periods_available"] == 2


def test_get_financial_statement_phan_biet_hai_dong_trung_item_id_bang_row_seq(con):
    """Ca quan trọng nhất: 'cost' xuất hiện 2 lần trong balance_sheet AAA
    (2 nhóm tài sản khác nhau) — phải trả về 2 item riêng biệt, không gộp
    nhầm thành 1 (đúng lý do row_seq tồn tại, spec §1.3)."""
    res = tools.get_financial_statement(con, "AAA", "balance_sheet")
    assert res["n_items"] == 2
    cost_items = [i for i in res["items"] if i["item_id"] == "cost"]
    assert len(cost_items) == 2
    vi_labels = {i["item_vi"] for i in cost_items}
    assert vi_labels == {"Nguyên giá TSCĐ hữu hình", "Nguyên giá tài sản đầu tư"}
    row_seqs = {i["row_seq"] for i in cost_items}
    assert row_seqs == {30, 40}


def test_get_financial_statement_ma_khong_co_du_lieu_tra_has_data_false(con):
    res = tools.get_financial_statement(con, "ZZZ", "income_statement")
    assert res["data_quality"]["has_data"] is False
    assert "n_items" not in res or res.get("items") in (None, [])


def test_get_financial_statement_period_type_khong_ton_tai_tra_has_data_false(con):
    """AAA có dữ liệu quarter nhưng fixture không có year — has_data phải
    phản ánh đúng THEO period_type được hỏi, không phải theo mã nói
    chung."""
    res = tools.get_financial_statement(con, "AAA", "income_statement", period_type="year")
    assert res["data_quality"]["has_data"] is False


# --- I2 (final review B2): cắt âm thầm khi 1 báo cáo nhiều dòng x nhiều kỳ ---

def test_get_financial_statement_bao_cao_lon_khong_bi_cat_am_tham(con):
    """Ca đã tái hiện được ở final review: báo cáo 208 dòng x 10 kỳ = 2.080
    dòng, vượt hằng số cứng limit=2000 của bản cũ — tool trả về ĐÚNG 200/208
    item trong khi data_quality.has_data=True, không tín hiệu nào báo bị
    cắt. Với n_periods=10, toàn bộ 208 dòng phải có mặt."""
    res = tools.get_financial_statement(con, "BIG", "balance_sheet", n_periods=10)
    assert res["n_items"] == 208, "mất dòng = đúng bug cũ đang tái hiện"
    assert res["data_quality"]["n_periods_returned"] == 10
    assert res["data_quality"]["n_periods_available"] == 10
    assert res["data_quality"]["truncated"] is False
    # mỗi item phải đủ cả 10 kỳ, không phải chỉ vài kỳ đầu
    assert all(len(i["values_by_period"]) == 10 for i in res["items"])


def test_get_financial_statement_n_periods_mac_dinh_cat_ky_nhung_bao_truncated(con):
    """Mặc định n_periods=8 trên mã có 10 kỳ: vẫn đủ 208 dòng (không mất
    dòng nào), nhưng phải BÁO truncated=True vì DB còn 2 kỳ chưa trả —
    khác hẳn bản cũ im lặng."""
    res = tools.get_financial_statement(con, "BIG", "balance_sheet")
    assert res["n_items"] == 208
    assert res["data_quality"]["n_periods_returned"] == 8
    assert res["data_quality"]["n_periods_available"] == 10
    assert res["data_quality"]["truncated"] is True


def test_get_financial_statement_lay_dung_n_ky_moi_nhat_qua_ranh_gioi_nam(con):
    """period_label là chuỗi ('2026-q2'), không phải ngày — kiểm thật rằng
    sort DESC theo chuỗi cho ra đúng thứ tự thời gian, kể cả khi cửa sổ vắt
    qua ranh giới năm (2026-q1 phải mới hơn 2025-q4)."""
    res = tools.get_financial_statement(con, "BIG", "balance_sheet", n_periods=3)
    periods = set(res["items"][0]["values_by_period"])
    assert periods == {"2026-q2", "2026-q1", "2025-q4"}
    assert res["data_quality"]["n_periods_returned"] == 3
    assert res["data_quality"]["truncated"] is True


def test_get_financial_statement_n_periods_lon_hon_du_lieu_khong_bao_truncated(con):
    res = tools.get_financial_statement(con, "BIG", "balance_sheet", n_periods=50)
    assert res["data_quality"]["n_periods_returned"] == 10
    assert res["data_quality"]["truncated"] is False


# --- I3 (final review B2): trôi dạt template, cùng row_seq khác item ---

def test_get_financial_statement_cung_row_seq_khac_item_khong_bi_gop(con):
    """Template BCTC của VCI đổi theo thời gian: row_seq=30 là "Nguyên giá
    TSCĐ hữu hình" ở 2026-q2 nhưng là "Hàng tồn kho" ở 2025-q1 (kỳ cũ vẫn
    còn trong bảng). Bản cũ gộp CHỈ theo row_seq -> trộn giá trị hai item
    khác nhau vào một chuỗi values_by_period mang tên item mới nhất, âm
    thầm, không tín hiệu lỗi. Phải trả về 2 item RIÊNG BIỆT."""
    res = tools.get_financial_statement(con, "DRIFT", "balance_sheet")

    seq30 = [i for i in res["items"] if i["row_seq"] == 30]
    assert len(seq30) == 2, "hai dòng khác nhau cùng row_seq bị gộp làm một"
    by_vi = {i["item_vi"]: i for i in seq30}
    assert set(by_vi) == {"Nguyên giá TSCĐ hữu hình", "Hàng tồn kho"}

    # Giá trị KHÔNG được trộn sang nhau
    assert by_vi["Nguyên giá TSCĐ hữu hình"]["values_by_period"] == {"2026-q2": 10.0}
    assert by_vi["Hàng tồn kho"]["values_by_period"] == {"2025-q1": 7.0}
    assert by_vi["Hàng tồn kho"]["item_id"] == "inventory"
    assert res["n_items"] == 3      # 2 dòng ở row_seq=30 + 1 dòng row_seq=31


# --- I6 (final review B2): tham số sai giá trị phải báo lỗi ---

def test_get_financial_statement_statement_type_sai_tra_error(con):
    """'cashflow' (sai chính tả, đúng là 'cash_flow') từng trả về y hệt
    payload "không có dữ liệu" như một mã thật sự không có BCTC — agent LLM
    tự tin kết luận sai."""
    res = tools.get_financial_statement(con, "AAA", "cashflow")
    assert "error" in res
    assert "cashflow" in res["error"]
    assert "data_quality" not in res


def test_get_financial_statement_period_type_sai_tra_error(con):
    res = tools.get_financial_statement(con, "AAA", "income_statement",
                                        period_type="quarterly")
    assert "error" in res
    assert "quarterly" in res["error"]
    assert "data_quality" not in res


def test_get_financial_statement_n_periods_khong_hop_le_tra_error(con):
    for bad in (0, -1):
        res = tools.get_financial_statement(con, "AAA", "income_statement",
                                            n_periods=bad)
        assert "error" in res, bad


def test_get_financial_statement_ma_khong_ton_tai_van_la_has_data_false(con):
    """Ranh giới quan trọng: tham số ĐÚNG nhưng mã không có dữ liệu vẫn là
    has_data=False (không phải error) — hai ca này phải phân biệt được."""
    res = tools.get_financial_statement(con, "ZZZ", "cash_flow")
    assert "error" not in res
    assert res["data_quality"]["has_data"] is False


# --- C1: get_thesis_update (luận điểm đầu tư định kỳ) ---

def test_current_scores_khop_5_diem_thanh_phan(con):
    r = tools._current_scores(con, "AAA")
    assert r == {
        "value": 80.0, "quality": 70.0, "growth": 60.0,
        "dividend": 90.0, "safety": 50.0,
    }


def test_current_scores_ma_khong_ton_tai_tra_none(con):
    assert tools._current_scores(con, "ZZZ") is None


def test_financial_trend_chi_tra_quy_sau_since_date_dung_thu_tu(con):
    r = tools._financial_trend(con, "AAA", "2026-01-01")
    assert r["n_new_quarters"] == 2
    quarters = r["quarters"]
    assert [(q["year"], q["quarter"]) for q in quarters] == [(2026, 1), (2026, 2)]


def test_financial_trend_loc_dung_since_date_cat_bot_qua_cu(con):
    r = tools._financial_trend(con, "AAA", "2026-04-01")
    assert r["n_new_quarters"] == 1
    assert [(q["year"], q["quarter"]) for q in r["quarters"]] == [(2026, 2)]


def test_financial_trend_khong_lan_dong_nam_quarter_5(con):
    """Dòng năm (quarter=5, period_type='year', period_end_date 2025-12-31)
    PHẢI bị loại dù since_date đủ cũ để bao trùm nó — bảo vệ đúng Global
    Constraint 'phải lọc period_type=quarter'."""
    r = tools._financial_trend(con, "AAA", "2020-01-01")
    assert r["n_new_quarters"] == 2
    assert all(q["quarter"] != 5 for q in r["quarters"])


def test_new_distribution_events_loc_dung_since_date(con):
    r = tools._new_distribution_events(con, "AAA", "2026-05-01")["items"]
    assert len(r) == 2
    # Sửa so với brief gốc: 2 literal gốc trong brief chỉ dài 19 ký tự (thiếu
    # 1 ký tự cuối so với tiêu đề thật cắt ở vị trí 20), nên literal[:20] là
    # no-op còn event_title_vi[:20] của dữ liệu thật lấy đủ 20 ký tự — 2 vế
    # không bao giờ khớp (đã tự xác minh: 'tiề' 19 ký tự vs 'tiền' 20 ký tự
    # của "Trả cổ tức bằng tiền mặt..."). Sửa literal cho đủ 20 ký tự, giữ
    # nguyên Ý ĐỊNH gốc (kiểm diện cả 2 tiêu đề sự kiện qua tiền tố cắt).
    assert {e["event_title_vi"][:20] for e in r} == {
        "Trả cổ tức bằng tiền", "Phát hành cổ phiếu -",
    }


def test_new_statement_periods_phat_hien_dung_ky_moi(con):
    r = tools._new_statement_periods(con, "AAA", "2026-06-01")["items"]
    assert len(r) == 1
    assert r[0]["period_label"] == "2026-q2"
    assert r[0]["statement_type"] == "income_statement"


def test_new_statement_periods_khong_co_gi_moi_tra_mang_rong(con):
    r = tools._new_statement_periods(con, "AAA", "2026-09-01")
    assert r["items"] == []
    assert r["truncated"] is False


def test_ownership_change_tinh_dung_delta_khi_co_baseline_that(con):
    r = tools._ownership_change(con, "AAA", "2026-06-01")
    assert r["baseline_snapshot_date"] == "2026-05-01"
    assert r["latest_snapshot_date"] == "2026-08-01"
    assert r["baseline_is_fallback"] is False
    assert r["top1_pct"]["baseline"] == pytest.approx(0.2400)
    assert r["top1_pct"]["latest"] == pytest.approx(0.2580)
    assert r["top1_pct"]["delta"] == pytest.approx(0.0180, abs=1e-6)
    assert r["insider_pct"]["baseline"] == pytest.approx(0.2400)
    assert r["insider_pct"]["latest"] == pytest.approx(0.3105)


def test_ownership_change_fallback_khi_khong_co_snapshot_truoc_since_date(con):
    """since_date quá xa (2026-01-01) -> không có snapshot nào <= mốc đó ->
    dùng snapshot CŨ NHẤT hiện có (2026-05-01) làm baseline, đặt cờ fallback."""
    r = tools._ownership_change(con, "AAA", "2026-01-01")
    assert r["baseline_snapshot_date"] == "2026-05-01"
    assert r["baseline_is_fallback"] is True


def test_ownership_change_chi_1_snapshot_delta_bang_0(con):
    r = tools._ownership_change(con, "GGG", "2026-01-01")
    assert r["baseline_snapshot_date"] == r["latest_snapshot_date"] == "2026-08-01"
    assert r["top1_pct"]["delta"] == 0.0


def test_ownership_change_khop_int_ownership_snapshot(con):
    """Tiêu chí hoàn thành #2 (spec §7): _ownership_change tự tính lại phép
    gộp và phải ra đúng con số kỳ vọng trên một bộ dữ liệu cố định.

    Important #6 (final review) — PHẠM VI THẬT của test này, đọc kỹ trước khi
    tin vào nó: vế "expected" đọc từ bảng int_ownership_snapshot GIẢ trong
    fixture, mà dòng GGG ở đó là một dòng VIẾT TAY, KHÔNG phải kết quả chạy
    model dbt thật (transforms/models/intermediate/int_ownership_snapshot.sql).
    Nói cách khác đây là test tái hiện phép tính số học trên dữ liệu cố định,
    KHÔNG PHẢI test tích hợp với dbt, và nó KHÔNG bảo vệ được khỏi trôi dạt
    công thức: nếu công thức gộp trong model dbt đổi, dòng viết tay không tự
    đổi theo nên test vẫn xanh trong khi 2 cài đặt đã lệch nhau. Việc chặn
    trôi dạt thật sự cần chạy `dbt build` trong CI — nợ kỹ thuật CI đã biết,
    ngoài phạm vi C1. Trong lúc chờ, ràng buộc được ghi bằng comment ở đầu
    file .sql kia (sửa công thức ở đó thì phải sửa _ownership_change).

    Dùng GGG vì dữ liệu ở đây được dựng nhất quán giữa 2 bảng (xem comment ở
    fixture) — dòng AAA của int_ownership_snapshot KHÔNG dùng được cho so
    sánh này (tạo cho mục đích khác từ B1)."""
    r = tools._ownership_change(con, "GGG", "2026-01-01")
    expected = db.run_query(
        con,
        "SELECT total_disclosed_pct, top1_pct, top5_pct, insider_pct "
        "FROM int_ownership_snapshot WHERE symbol = 'GGG'",
        limit=1,
    )[0]
    assert r["total_disclosed_pct"]["latest"] == pytest.approx(expected["total_disclosed_pct"])
    assert r["top1_pct"]["latest"] == pytest.approx(expected["top1_pct"])
    assert r["top5_pct"]["latest"] == pytest.approx(expected["top5_pct"])
    assert r["insider_pct"]["latest"] == pytest.approx(expected["insider_pct"])


def test_ownership_change_ma_khong_co_du_lieu_so_huu_tra_none(con):
    assert tools._ownership_change(con, "ZZZ", "2026-01-01") is None


def test_ownership_change_officer_lech_ngay_khong_bia_delta_am(con):
    """Critical #1 (final review): stg_shareholder và stg_officer có thể LỆCH
    tập snapshot_date cho CÙNG một mã — fetch_shareholders/fetch_officers bọc
    `except Exception: continue` RIÊNG theo từng mã nên một lần chạy monthly
    có thể lấy được cổ đông mà hỏng officer. HHH: cổ đông có 2 mốc, officer
    CHỈ có 2026-05-01.

    Bản cũ lọc stg_officer bằng ngày CỦA CỔ ĐÔNG nên mốc latest (2026-08-01)
    không khớp dòng officer nào -> sum([]) = 0.0 -> báo insider_pct delta
    = -0.1200, tức "nội bộ đã bán sạch 12% cổ phần" — hoàn toàn GIẢ, lại kèm
    baseline_is_fallback=False nên trông như dữ liệu đáng tin.

    Đúng: trục thời gian của officer được chọn RIÊNG trên tập ngày của chính
    stg_officer (đúng cách int_ownership_snapshot.officer_snapshot_date làm)
    -> cả 2 mốc đều là 2026-05-01 -> insider_pct không đổi, và payload phơi
    rõ 2 trục ngày có thể khác nhau."""
    r = tools._ownership_change(con, "HHH", "2026-06-01")
    assert r["baseline_snapshot_date"] == "2026-05-01"
    assert r["latest_snapshot_date"] == "2026-08-01"
    # Trục officer RIÊNG — dừng ở 2026-05-01 vì không có snapshot mới hơn.
    assert r["officer_baseline_snapshot_date"] == "2026-05-01"
    assert r["officer_latest_snapshot_date"] == "2026-05-01"
    assert r["insider_pct"]["baseline"] == pytest.approx(0.1200)
    assert r["insider_pct"]["latest"] == pytest.approx(0.1200)
    assert r["insider_pct"]["delta"] == pytest.approx(0.0)
    # Phần cổ đông vẫn dùng trục ngày của cổ đông, không bị ảnh hưởng.
    assert r["top1_pct"]["delta"] == pytest.approx(0.0100, abs=1e-6)


def test_ownership_change_khong_co_officer_tra_insider_none_khong_phai_0(con):
    """Critical #1: mã chưa từng fetch được officer nào (KKK) -> insider_pct
    phải là None ("không có dữ liệu"), KHÔNG PHẢI 0.0 ("nội bộ sở hữu 0%") —
    hai chuyện khác hẳn nhau với người đọc luận điểm. delta cũng phải None:
    không tính latest - baseline khi một vế không tồn tại."""
    r = tools._ownership_change(con, "KKK", "2026-06-01")
    assert r["officer_baseline_snapshot_date"] is None
    assert r["officer_latest_snapshot_date"] is None
    assert r["insider_pct"]["baseline"] is None
    assert r["insider_pct"]["latest"] is None
    assert r["insider_pct"]["delta"] is None
    # Phần cổ đông vẫn tính bình thường, không bị kéo theo.
    assert r["top1_pct"]["delta"] == pytest.approx(0.0100, abs=1e-6)


def test_get_thesis_update_lap_rap_du_4_khoi(con):
    r = tools.get_thesis_update(con, "AAA", "2026-01-01")
    assert r["symbol"] == "AAA"
    assert r["since_date"] == "2026-01-01"
    assert r["current_scores"]["quality"] == 70.0
    assert r["financial_trend"]["n_new_quarters"] == 2
    assert len(r["new_distribution_events"]) == 2
    assert len(r["new_statement_periods"]) == 2
    assert r["ownership_change"]["baseline_is_fallback"] is True


def test_get_thesis_update_since_date_none_mac_dinh_90_ngay(con, monkeypatch):
    import datetime
    fixed_today = datetime.date(2026, 8, 19)

    class _FixedDate(datetime.date):
        @classmethod
        def today(cls):
            return fixed_today

    monkeypatch.setattr(tools, "date", _FixedDate)
    r = tools.get_thesis_update(con, "AAA", None)
    assert r["since_date"] == "2026-05-21"


def test_get_thesis_update_ma_hoan_toan_khong_ton_tai_tra_error(con):
    r = tools.get_thesis_update(con, "ZZZ", "2026-01-01")
    assert "error" in r


def test_get_thesis_update_since_date_sai_dinh_dang_tra_error(con):
    """Important #2 (final review): since_date phải được chuẩn hoá TRƯỚC khi
    vào helper. 3 khối dùng SQL nên DuckDB tự cast được "2026/01/01", nhưng
    _ownership_change so sánh CHUỖI theo thứ tự từ điển: '-' (0x2D) đứng
    trước '/' (0x2F) nên MỌI snapshot đều <= since_date -> baseline trùng
    latest -> mọi delta = 0.0 kèm baseline_is_fallback=False, tức tool báo
    "không có gì thay đổi" trong khi top1_pct thực tế đổi +1,8 điểm %.
    Tái hiện thật trước khi sửa. Nay chặn ngay ở cửa thay vì để 4 khối trả
    lời khác nhau trên cùng một input."""
    r = tools.get_thesis_update(con, "AAA", "2026/01/01")
    assert "error" in r
    assert "YYYY-MM-DD" in r["error"]


def test_hai_khoi_danh_sach_bao_truncated_khi_cham_tran(con, monkeypatch):
    """Important #4 (final review): chạm trần dòng phải được BÁO, không cắt
    âm thầm — đúng convention data_quality.truncated mà B2 đã lập cho
    get_financial_statement. Hạ trần xuống 1 thay vì bơm 50+ dòng vào fixture:
    thứ cần khoá là LOGIC báo cờ, không phải con số 50."""
    monkeypatch.setattr(tools, "_THESIS_LIST_ROW_LIMIT", 1)
    ev = tools._new_distribution_events(con, "AAA", "2026-05-01")
    assert len(ev["items"]) == 1
    assert ev["truncated"] is True

    st = tools._new_statement_periods(con, "AAA", "2026-01-01")
    assert len(st["items"]) == 1
    assert st["truncated"] is True


def test_get_thesis_update_co_khoi_data_quality_du_khoa(con):
    """Important #5 (final review): bản trước THIẾU HẲN data_quality — vi phạm
    quy ước chung (mọi tool khác đều trả) lẫn hợp đồng spec C1 §4.1 tự khai
    báo. Lõi phải giống _data_quality() dùng chung, cộng các tín hiệu riêng
    của C1."""
    dq = tools.get_thesis_update(con, "AAA", "2026-06-01")["data_quality"]
    # Lõi dùng chung với get_stock_profile/get_valuation_history.
    assert dq["data_quality_score"] == tools._data_quality(con, "AAA")["data_quality_score"]
    assert "quality_flags" in dq and "reliable" in dq
    # since_date 2026-06-01 có snapshot 2026-05-01 đứng trước -> baseline THẬT.
    assert dq["has_ownership_baseline"] is True
    assert dq["n_snapshots_available"] == 2
    assert dq["n_officer_snapshots_available"] == 2
    assert dq["distribution_events_truncated"] is False
    assert dq["statement_periods_truncated"] is False


def test_data_quality_bao_baseline_gia_khi_phai_fallback(con):
    """has_ownership_baseline=False là tín hiệu quan trọng nhất của khối này:
    baseline chỉ là snapshot CŨ NHẤT có sẵn, không phải mốc người dùng hỏi."""
    dq = tools.get_thesis_update(con, "AAA", "2026-01-01")["data_quality"]
    assert dq["has_ownership_baseline"] is False


def test_data_quality_ma_khong_co_du_lieu_so_huu_tra_none(con):
    """Mã không có dòng sở hữu nào -> 2 chỉ số snapshot là None ("không biết"),
    không phải 0 (dễ đọc nhầm thành "đã kiểm và đúng bằng 0")."""
    dq = tools.get_thesis_update(con, "CCC", "2026-01-01")["data_quality"]
    assert dq["has_ownership_baseline"] is False
    assert dq["n_snapshots_available"] is None
    assert dq["n_officer_snapshots_available"] is None


def test_get_thesis_update_since_date_dung_dinh_dang_van_chay_binh_thuong(con):
    """Bản sửa Important #2 không được đụng đến ca hợp lệ."""
    r = tools.get_thesis_update(con, "AAA", "2026-01-01")
    assert "error" not in r
    assert r["since_date"] == "2026-01-01"
    assert r["ownership_change"]["baseline_snapshot_date"] == "2026-05-01"
    assert r["ownership_change"]["baseline_is_fallback"] is True


def test_new_distribution_events_khong_co_gi_moi_tra_mang_rong(con):
    r = tools._new_distribution_events(con, "AAA", "2026-06-01")
    assert r["items"] == []
    assert r["truncated"] is False


# Bổ sung so với brief gốc (không có trong task-1-brief.md): khoá lại đúng
# thứ tự _date_str() TRƯỚC _clean() — cùng bài học A3 đã ghi trong docstring
# _date_str(): cột DATE qua .df() ra pandas.Timestamp, _clean() tự chuyển
# thành chuỗi qua .isoformat() (rò rỉ "T00:00:00") TRƯỚC KHI _date_str() kịp
# .date() nó, nếu áp _date_str() SAU _clean() như trong bản nháp đầu của
# brief. Đã tự xác minh thực nghiệm bằng thực thi trực tiếp (không tin vào
# giả định trước khi sửa).
def test_new_distribution_events_ngay_dung_dinh_dang_iso(con):
    r = tools._new_distribution_events(con, "AAA", "2026-05-01")["items"]
    by_date = sorted(e["exright_date"] for e in r)
    assert by_date == ["2026-05-11", "2026-05-25"]


# --- Task 4 (D): get_exchange_rate_history + get_recent_news ---

def test_get_exchange_rate_history_tra_dung_chuoi_theo_ngay(con):
    res = tools.get_exchange_rate_history(con, "USD", 30)
    assert res["currency_code"] == "USD"
    history = res["history"]
    assert len(history) == 2
    assert history[0]["rate_date"] == "2026-08-20"  # mới nhất trước


def test_get_exchange_rate_history_buy_cash_null_giu_none(con):
    res = tools.get_exchange_rate_history(con, "DKK", 30)
    assert res["history"][0]["buy_cash"] is None


def test_get_exchange_rate_history_ma_khong_ton_tai_tra_has_data_false(con):
    res = tools.get_exchange_rate_history(con, "ZZZ", 30)
    assert res["data_quality"]["has_data"] is False


def test_get_recent_news_tra_dung_thu_tu_moi_nhat_truoc(con):
    res = tools.get_recent_news(con, "HPG", 10)
    assert res["data_quality"]["has_data"] is True
    titles = [n["news_title"] for n in res["news"]]
    assert titles == ["Tiêu đề mới nhất", "Tiêu đề cũ hơn"]


def test_get_recent_news_ma_ngoai_portfolio_has_data_false_co_ghi_chu(con):
    res = tools.get_recent_news(con, "VCB", 10)
    assert res["data_quality"]["has_data"] is False
    assert "portfolio" in res["data_quality"]["note"].lower() or "danh mục" in res["data_quality"]["note"].lower()


def test_get_recent_news_cat_short_content_toi_da_300_ky_tu(con):
    # Fixture `con` của file này mở read_only=True — không INSERT được ở
    # thời điểm chạy test (khác brief gốc). Dòng nội dung dài đã được nướng
    # sẵn vào build_fake_mart() cho mã MLS (xem tests/conftest_mart.py).
    res = tools.get_recent_news(con, "MLS", 10)
    n3 = next(n for n in res["news"] if n["news_title"] == "Tin dài")
    assert len(n3["news_short_content"]) <= 300


def test_get_recent_news_content_null_giu_nguyen_none_khong_thanh_chuoi_rong(con):
    # Final whole-branch review (mục I1): nguồn VCI thực tế 100% NULL
    # news_short_content/news_source_link — code KHÔNG được coerce NULL
    # thành "" (đúng lớp lỗi "NULL rò rỉ thành giá trị mơ hồ" từng xảy ra ở
    # C2 với event_title_vi → literal "None"). Dòng n4 (mã IDV) nướng sẵn
    # NULL cho 2 trường này trong tests/conftest_mart.py.
    res = tools.get_recent_news(con, "IDV", 10)
    n4 = next(n for n in res["news"] if n["news_title"] == "Tin không có tóm tắt")
    assert n4["news_short_content"] is None
    assert n4["news_source_link"] is None


# --- Mảng Q: phễu tất định, cổng biến cố, định giá hiện tại ----------------

def test_screen_graham_gia_tri_trả_đủ_khối(con):
    res = tools.screen_graham(con, "gia_tri", limit=10)
    assert res["lens"] == "gia_tri"
    assert res["config_version"]
    assert [s["id"] for s in res["steps"]][0] == "vu_tru"
    assert [r["symbol"] for r in res["phan_tich_tiep"]] == ["AAA"]
    assert res["phan_tich_tiep"][0]["price_as_of"] == "2026-08-07"   # không rò "T00:00:00"
    assert res["benchmark"]["index_code"] == "VNINDEX"
    assert res["benchmark"]["trade_date"] == "2026-08-07"
    assert "price_as_of" in res and "ratio_as_of" in res


def test_screen_graham_gọi_hai_lần_giống_hệt(con):
    a = tools.screen_graham(con, "gia_tri")
    b = tools.screen_graham(con, "gia_tri")
    assert a == b


def test_screen_graham_lăng_kính_lạ_ném_lỗi(con):
    with pytest.raises(ValueError):
        tools.screen_graham(con, "luot_song")


def test_screen_graham_tang_truong_chạy_được(con):
    res = tools.screen_graham(con, "tang_truong")
    assert res["lens"] == "tang_truong"
    assert all(s["remaining"] >= 0 for s in res["steps"])


def test_get_risk_flags_mã_bị_chặn(con):
    res = tools.get_risk_flags(con, "ccc")
    assert res["risk_gate"] == "cho_bctc_ke_tiep"
    assert res["flags"][0]["code"] == "lo_quy_gan_day"
    assert res["profit_as_of"] == "2026-06-30"
    assert "cho_bctc_ke_tiep" in res["gate_meaning"]


def test_get_risk_flags_mã_lạ(con):
    assert "error" in tools.get_risk_flags(con, "ZZZ")


def test_get_stock_profile_có_định_giá_hiện_tại_và_rủi_ro(con):
    res = tools.get_stock_profile(con, "AAA")
    assert res["valuation_current"]["pe"] == 8.6
    assert res["valuation_current"]["band"] == "rất rẻ"
    assert res["quarterly_profit"]["loss_quarters_4q_actual"] == 0
    assert res["quarterly_profit"]["as_of"] == "2026-06-30"
    assert res["risk"] == {"gate": "qua", "flags": []}
    ccc = tools.get_stock_profile(con, "CCC")
    assert ccc["risk"]["gate"] == "cho_bctc_ke_tiep"
    assert ccc["risk"]["flags"][0]["severity"] == "nghiem_trong"
