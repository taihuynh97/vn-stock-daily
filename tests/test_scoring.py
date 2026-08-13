import pandas as pd
import pytest

from src import scoring


def _profile():
    return {
        "label": "Test",
        "universe": {
            "exchanges": ["HOSE", "HNX"],
            "min_market_cap_vnd": 1_000_000_000_000,
            "min_avg_turnover_20d_vnd": 1_000_000_000,
            "min_data_quality_score": 60,
        },
        "weights": {"value": 0.25, "quality": 0.30, "dividend": 0.30,
                    "growth": 0.05, "safety": 0.10},
        "require": {"dividend_years_min": 3, "roe_avg_8q_min": 0.12},
    }


def _rows():
    return pd.DataFrame([
        # đủ điều kiện, điểm cao
        {"symbol": "AAA", "exchange": "HOSE", "market_cap": 5e12,
         "avg_turnover_20d": 5e9, "data_quality_score": 90,
         "dividend_years_consecutive": 5, "roe_avg_8q": 0.18,
         "value_score": 80.0, "quality_score": 70.0, "growth_score": 60.0,
         "dividend_score": 90.0, "safety_score": 50.0},
        # thiếu quality_score (NULL) → phải bị loại vì weight quality > 0
        {"symbol": "BBB", "exchange": "HOSE", "market_cap": 5e12,
         "avg_turnover_20d": 5e9, "data_quality_score": 90,
         "dividend_years_consecutive": 5, "roe_avg_8q": 0.18,
         "value_score": 80.0, "quality_score": None, "growth_score": 60.0,
         "dividend_score": 90.0, "safety_score": 50.0},
        # sàn UPCOM → ngoài universe
        {"symbol": "CCC", "exchange": "UPCOM", "market_cap": 5e12,
         "avg_turnover_20d": 5e9, "data_quality_score": 90,
         "dividend_years_consecutive": 5, "roe_avg_8q": 0.18,
         "value_score": 80.0, "quality_score": 70.0, "growth_score": 60.0,
         "dividend_score": 90.0, "safety_score": 50.0},
        # cổ tức chỉ 1 năm → không đạt require
        {"symbol": "DDD", "exchange": "HOSE", "market_cap": 5e12,
         "avg_turnover_20d": 5e9, "data_quality_score": 90,
         "dividend_years_consecutive": 1, "roe_avg_8q": 0.18,
         "value_score": 80.0, "quality_score": 70.0, "growth_score": 60.0,
         "dividend_score": 90.0, "safety_score": 50.0},
        # thanh khoản quá thấp
        {"symbol": "EEE", "exchange": "HOSE", "market_cap": 5e12,
         "avg_turnover_20d": 1e8, "data_quality_score": 90,
         "dividend_years_consecutive": 5, "roe_avg_8q": 0.18,
         "value_score": 80.0, "quality_score": 70.0, "growth_score": 60.0,
         "dividend_score": 90.0, "safety_score": 50.0},
    ])


def test_compute_composite_weighted_sum():
    out = scoring.compute_composite(_rows(), _profile())
    aaa = out[out.symbol == "AAA"].iloc[0]
    expected = (80 * 0.25 + 70 * 0.30 + 90 * 0.30 + 60 * 0.05 + 50 * 0.10)
    assert aaa["composite_score"] == pytest.approx(expected, abs=0.01)


def test_compute_composite_null_component_is_not_zero():
    """Thành phần NULL mà profile có trọng số > 0 → không chấm, KHÔNG tính là 0."""
    out = scoring.compute_composite(_rows(), _profile())
    bbb = out[out.symbol == "BBB"].iloc[0]
    assert pd.isna(bbb["composite_score"])
    assert "quality" in bbb["components_missing"]


def test_apply_universe_filters_exchange_liquidity_and_require():
    ok, rejected = scoring.apply_universe(_rows(), _profile())
    assert set(ok["symbol"]) == {"AAA", "BBB"}
    reasons = dict(zip(rejected["symbol"], rejected["reject_reason"]))
    assert "sàn" in reasons["CCC"]
    assert "cổ tức" in reasons["DDD"]
    assert "thanh khoản" in reasons["EEE"]


def test_zero_weight_component_may_be_null():
    """Nếu profile gán trọng số 0 cho một thành phần, thành phần đó NULL vẫn OK."""
    prof = _profile()
    prof["weights"] = {"value": 0.5, "quality": 0.0, "dividend": 0.5,
                       "growth": 0.0, "safety": 0.0}
    out = scoring.compute_composite(_rows(), prof)
    bbb = out[out.symbol == "BBB"].iloc[0]
    assert bbb["composite_score"] == pytest.approx(80 * 0.5 + 90 * 0.5, abs=0.01)


def test_load_profiles_reads_three_profiles():
    profiles = scoring.load_profiles()
    assert {"bluechip_dividend", "deep_value", "quality_growth"} <= set(profiles["profiles"])
    for name, p in profiles["profiles"].items():
        total = sum(p["weights"].values())
        assert total == pytest.approx(1.0, abs=1e-6), f"{name} tổng trọng số != 1"


def test_load_profiles_merges_universe_defaults():
    profiles = scoring.load_profiles()
    p = profiles["profiles"]["bluechip_dividend"]
    assert p["universe"]["exchanges"] == ["HOSE", "HNX"]      # từ universe_defaults
    assert p["universe"]["min_market_cap_vnd"] == 5_000_000_000_000


def test_load_profiles_rejects_unknown_universe_key(tmp_path):
    """Khoá cấu hình không được code nào áp phải NỔ, không được im lặng bỏ qua.

    Đây là lỗi thật đã gặp: `min_quarters_history` từng nằm trong
    universe_defaults mà không code nào đọc, nên nó là một filter rỗng —
    người dùng đặt ngưỡng và tin là đã lọc.
    """
    p = tmp_path / "profiles.yml"
    p.write_text(
        "default_profile: x\n"
        "universe_defaults: {exchanges: [HOSE]}\n"
        "profiles:\n"
        "  x:\n"
        "    universe: {min_pe_ratio: 15}\n"
        "    weights: {value: 1.0, quality: 0.0, growth: 0.0,\n"
        "              dividend: 0.0, safety: 0.0}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="min_pe_ratio"):
        scoring.load_profiles(p)


def test_load_profiles_rejects_weights_not_summing_to_one(tmp_path):
    p = tmp_path / "profiles.yml"
    p.write_text(
        "default_profile: x\n"
        "profiles:\n"
        "  x:\n"
        "    universe: {}\n"
        "    weights: {value: 0.5, quality: 0.2, growth: 0.0,\n"
        "              dividend: 0.0, safety: 0.0}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="tổng trọng số"):
        scoring.load_profiles(p)


def test_apply_universe_filters_min_quarters_history():
    """`min_quarters_history` phải THẬT SỰ lọc, không phải khoá trang trí."""
    rows = _rows().copy()
    rows["quarters_available"] = [20, 20, 20, 20, 20]
    rows.loc[rows.symbol == "AAA", "quarters_available"] = 8

    prof = _profile()
    prof["universe"]["min_quarters_history"] = 12

    ok, rejected = scoring.apply_universe(rows, prof)
    assert "AAA" not in set(ok["symbol"])
    reasons = dict(zip(rejected["symbol"], rejected["reject_reason"]))
    assert "quý" in reasons["AAA"]


# --- Vòng sửa 1 (review): reject_reason phải liệt kê ĐẦY ĐỦ, không chỉ lý do
# đầu tiên khớp — đo thực tế trên production: 85,5%-96,4% mã bị loại trượt từ
# 2 điều kiện trở lên. Bản trước dùng `reasons == ""` để chỉ ghi lý do đầu,
# nên một mã trượt cả sàn lẫn vốn hoá chỉ hiện "ngoài sàn cho phép".

def test_apply_universe_lists_all_matching_reasons_not_just_first():
    """Một mã trượt nhiều điều kiện cùng lúc phải liệt kê đủ mọi lý do."""
    rows = _rows().copy()
    # CCC vốn chỉ trượt sàn (UPCOM) trong _rows(); hạ thêm vốn hoá để nó trượt
    # CẢ HAI điều kiện cùng lúc.
    rows.loc[rows.symbol == "CCC", "market_cap"] = 1e9

    ok, rejected = scoring.apply_universe(rows, _profile())
    reasons = dict(zip(rejected["symbol"], rejected["reject_reason"]))
    assert "sàn" in reasons["CCC"]
    assert "vốn hoá" in reasons["CCC"]


def test_load_profiles_rejects_unknown_require_key(tmp_path):
    """Cùng lớp lỗi với khoá universe lạ, nhưng ở phía `require`."""
    p = tmp_path / "profiles.yml"
    p.write_text(
        "default_profile: x\n"
        "profiles:\n"
        "  x:\n"
        "    universe: {}\n"
        "    weights: {value: 1.0, quality: 0.0, growth: 0.0,\n"
        "              dividend: 0.0, safety: 0.0}\n"
        "    require: {min_pe_ratio: 15}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="min_pe_ratio"):
        scoring.load_profiles(p)


def test_load_profiles_rejects_unknown_weight_component(tmp_path):
    """Thành phần điểm không tồn tại (vd. gõ nhầm tên) phải nổ, không âm thầm bỏ qua."""
    p = tmp_path / "profiles.yml"
    p.write_text(
        "default_profile: x\n"
        "profiles:\n"
        "  x:\n"
        "    universe: {}\n"
        "    weights: {value: 1.0, quality: 0.0, growth: 0.0,\n"
        "              dividend: 0.0, safety: 0.0, momentum: 0.0}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="momentum"):
        scoring.load_profiles(p)


# --- Vòng sửa 1 (review, Minor 3): screen()/screen_report() là hai hàm cửa
# vào chính, trước đó chỉ được kiểm tay trên production. Giả lập connection
# bằng một object nhỏ có .execute(sql).df() -> DataFrame, không cần DuckDB
# hay MotherDuck thật.

class _FakeResult:
    def __init__(self, df):
        self._df = df

    def df(self):
        return self._df


class _FakeConn:
    """Giả lập DuckDBPyConnection tối giản: chỉ cần .execute(sql).df()."""

    def __init__(self, df):
        self._df = df

    def execute(self, sql):
        return _FakeResult(self._df)


def _screen_rows():
    base = {"exchange": "HOSE", "market_cap": 5e12, "avg_turnover_20d": 5e9,
            "data_quality_score": 90, "dividend_years_consecutive": 5,
            "roe_avg_8q": 0.18}
    return pd.DataFrame([
        # 3 mã chấm được, điểm khác nhau rõ để kiểm thứ tự xếp hạng.
        {**base, "symbol": "HIGH", "value_score": 90.0, "quality_score": 90.0,
         "growth_score": 90.0, "dividend_score": 90.0, "safety_score": 90.0},
        {**base, "symbol": "MID", "value_score": 50.0, "quality_score": 50.0,
         "growth_score": 50.0, "dividend_score": 50.0, "safety_score": 50.0},
        {**base, "symbol": "LOW", "value_score": 10.0, "quality_score": 10.0,
         "growth_score": 10.0, "dividend_score": 10.0, "safety_score": 10.0},
        # đủ điều kiện universe nhưng thiếu quality_score -> không chấm được.
        {**base, "symbol": "NOSCORE", "value_score": 80.0, "quality_score": None,
         "growth_score": 60.0, "dividend_score": 90.0, "safety_score": 50.0},
        # ngoài sàn cho phép -> bị loại trước khi tới compute_composite.
        {**base, "symbol": "OUT", "exchange": "UPCOM", "value_score": 99.0,
         "quality_score": 99.0, "growth_score": 99.0, "dividend_score": 99.0,
         "safety_score": 99.0},
    ])


def _fake_get_profile(monkeypatch):
    def _get(profile_name=None, path=None):
        p = _profile()
        p["name"] = profile_name or "test"
        return p
    monkeypatch.setattr(scoring, "get_profile", _get)


def test_screen_ranks_descending_rank_from_one_and_respects_limit(monkeypatch):
    _fake_get_profile(monkeypatch)
    con = _FakeConn(_screen_rows())
    out = scoring.screen(con, "test", limit=2)
    assert list(out["rank"]) == [1, 2]
    assert list(out["symbol"]) == ["HIGH", "MID"]  # LOW bị cắt vì limit=2
    assert out["composite_score"].is_monotonic_decreasing
    assert "NOSCORE" not in set(out["symbol"])
    assert "OUT" not in set(out["symbol"])


def test_screen_report_separates_ranked_unscored_and_rejected(monkeypatch):
    _fake_get_profile(monkeypatch)
    con = _FakeConn(_screen_rows())
    r = scoring.screen_report(con, "test", limit=10)
    assert set(r["ranked"]["symbol"]) == {"HIGH", "MID", "LOW"}
    assert set(r["unscored"]["symbol"]) == {"NOSCORE"}
    assert r["universe_size"] == 4        # tất cả trừ OUT (ngoài sàn)
    assert r["rejected_total"] == 1
    assert r["rejected_counts"] == {"ngoài sàn cho phép": 1}
