"""Phễu sàng lọc tất định (mảng Q, Task 7).

Mục tiêu gốc: cùng câu hỏi + cùng dữ liệu → cùng kết quả. Trước mảng Q mỗi lần
sàng lọc là một câu SQL tự viết với ngưỡng khác nhau (03/09, 10/09, 12/09).
"""
import pandas as pd
import pytest

from src import graham_screen


def _row(sym, **kw):
    base = dict(
        symbol=sym, company_name=f"Cty {sym}", exchange="HOSE", com_class="NONFIN",
        industry_lv2="Ngành X", market_cap=5e12, market_cap_current=5e12,
        avg_turnover_20d=5e9, data_quality_score=90.0, is_loss_making=False,
        loss_quarters_4q_actual=0.0, loss_quarters_12q_actual=0.0,
        pe_current=8.0, pb_current=1.0, dividend_years_consecutive=6.0,
        current_ratio=2.0, roe_avg_8q=0.20, roe_stability=0.8,
        earnings_cagr_3y=0.15, revenue_cagr_3y=0.10, growth_consistency=0.8,
        quality_score=70.0, growth_score=60.0, value_score=70.0,
        risk_gate="qua", risk_flags="[]", last_close=10000.0,
        price_as_of="2026-10-02", ratio_as_of="2026-06-30",
    )
    base.update(kw)
    return base


def _df():
    return pd.DataFrame([
        _row("AAA", pe_current=6.0, pb_current=1.0),                    # tích 6 → qua cả biên an toàn
        _row("BBB", pe_current=9.0, pb_current=1.0),                    # tích 9
        _row("CCC", pe_current=6.0, pb_current=1.0,
             loss_quarters_12q_actual=1.0, loss_quarters_4q_actual=1.0),  # quý lỗ thật → loại
        _row("DDD", pe_current=None, pb_current=1.0),                   # P/E không đo được
        _row("EEE", com_class="BANK", current_ratio=None,
             pe_current=7.0, pb_current=1.2),                           # ngân hàng: thanh toán N/A
        _row("FFF", pe_current=5.0, pb_current=1.0,
             risk_gate="cho_bctc_ke_tiep"),                             # qua phễu nhưng bị chặn
        _row("GGG", pe_current=12.0, pb_current=1.5),                   # tích 18 → trượt biên an toàn
        _row("HHH", exchange="UPCOM"),                                  # ngoài vũ trụ
        _row("III", current_ratio=1.2),                                 # NONFIN thanh toán yếu
        _row("JJJ", loss_quarters_12q_actual=None),                     # không kiểm được quý lỗ
        _row("KKK", pe_current=6.0, pb_current=1.0),                    # hoà với AAA → xếp theo mã
    ])


@pytest.fixture
def cfg():
    return graham_screen.load_config()


def test_config_có_version_và_hai_lăng_kính(cfg):
    assert cfg["version"]
    assert set(cfg["lenses"]) == {"gia_tri", "tang_truong"}


def test_chạy_hai_lần_giống_hệt(cfg):
    a = graham_screen.run(_df(), "gia_tri", cfg)
    b = graham_screen.run(_df().sample(frac=1, random_state=7), "gia_tri", cfg)
    assert a["steps"] == b["steps"]
    pd.testing.assert_frame_equal(a["passed"], b["passed"])
    pd.testing.assert_frame_equal(a["waiting"], b["waiting"])


def test_gia_tri_kết_quả_và_thứ_tự(cfg):
    res = graham_screen.run(_df(), "gia_tri", cfg)
    assert list(res["passed"]["symbol"]) == ["AAA", "KKK", "EEE", "BBB"]
    assert list(res["waiting"]["symbol"]) == ["FFF"]
    assert res["lens"] == "gia_tri" and res["config_version"] == cfg["version"]


def test_gia_tri_đếm_từng_bước(cfg):
    res = graham_screen.run(_df(), "gia_tri", cfg)
    counts = {s["id"]: s["remaining"] for s in res["steps"]}
    assert counts["vu_tru"] == 10          # HHH (UPCOM) bị loại
    assert counts["co_lai"] == 8           # CCC (quý lỗ) và JJJ (không kiểm được) bị loại
    assert counts["pe_toi_da"] == 7        # DDD (P/E NULL) bị loại, không lỗi
    assert counts["thanh_toan"] == 6       # III bị loại; EEE (BANK) giữ lại
    assert counts["bien_an_toan"] == 5     # GGG trượt (tích 18 > 10)


def test_mã_không_kiểm_được_quý_lỗ_được_báo_riêng(cfg):
    res = graham_screen.run(_df(), "gia_tri", cfg)
    assert "JJJ" in res["unverifiable"]


def test_tang_truong_chạy_được_và_tất_định(cfg):
    df = _df()
    df.loc[df.symbol == "BBB", "growth_score"] = 90.0
    res = graham_screen.run(df, "tang_truong", cfg)
    syms = list(res["passed"]["symbol"])
    assert syms[0] == "BBB"
    assert "CCC" not in syms and "HHH" not in syms
    assert syms == sorted(syms, key=lambda s: (-float(
        df.set_index("symbol").loc[s, ["quality_score", "growth_score"]].mean()), s))


def test_lăng_kính_lạ_ném_lỗi(cfg):
    with pytest.raises(ValueError):
        graham_screen.run(_df(), "luot_song", cfg)


def test_thiếu_cột_đầu_vào_ném_lỗi_rõ_ràng(cfg):
    with pytest.raises(KeyError):
        graham_screen.run(_df().drop(columns=["pe_current"]), "gia_tri", cfg)
