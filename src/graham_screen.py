"""Phễu sàng lọc tất định theo lăng kính (mảng Q).

Hàm thuần trên DataFrame — tool MCP `screen_graham` dựng DataFrame từ
warehouse rồi gọi `run()`. Không đọc dữ liệu, không ghi gì: dễ kiểm thử và
cùng đầu vào luôn cho cùng đầu ra (thứ tự dòng đầu vào không ảnh hưởng).

Ngưỡng nằm ở config/graham_screen.yml (có `version`). Mỗi bước trả về số mã
còn lại để người đọc thấy phễu cắt ở đâu. Mã qua phễu nhưng có
`risk_gate = 'cho_bctc_ke_tiep'` bị tách sang `waiting` — chưa định giá được.
"""
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT / "config" / "graham_screen.yml"

REQUIRED_COLUMNS = {
    "symbol", "exchange", "com_class", "market_cap", "market_cap_current",
    "avg_turnover_20d", "data_quality_score", "is_loss_making",
    "loss_quarters_12q_actual", "pe_current", "pb_current",
    "dividend_years_consecutive", "current_ratio", "roe_avg_8q", "roe_stability",
    "earnings_cagr_3y", "revenue_cagr_3y", "growth_consistency",
    "quality_score", "growth_score", "risk_gate",
}

OUTPUT_COLUMNS = [
    "symbol", "company_name", "exchange", "com_class", "industry_lv2",
    "last_close", "pe_current", "pb_current", "pe_x_pb", "price_to_graham",
    "dividend_years_consecutive", "roe_avg_8q", "roe_stability",
    "earnings_cagr_3y", "revenue_cagr_3y", "quality_score", "growth_score",
    "value_score", "market_cap_current", "avg_turnover_20d",
    "loss_quarters_4q_actual", "risk_gate", "risk_flags",
    "price_as_of", "ratio_as_of",
]

WAIT_GATE = "cho_bctc_ke_tiep"


def load_config(path=None) -> dict:
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not cfg.get("version"):
        raise ValueError("graham_screen.yml thiếu `version`")
    for name, lens in cfg.get("lenses", {}).items():
        for st in lens.get("steps", []):
            if st["id"] not in _STEPS:
                raise ValueError(f"Lăng kính '{name}': bước lạ '{st['id']}'. Có: {sorted(_STEPS)}")
        if lens.get("sort") not in _SORTS:
            raise ValueError(f"Lăng kính '{name}': cách xếp lạ '{lens.get('sort')}'")
    return cfg


def _num(df, col):
    return pd.to_numeric(df[col], errors="coerce")


def _vu_tru(df, st, lens):
    u = lens["universe"]
    mcap = _num(df, "market_cap_current").fillna(_num(df, "market_cap"))
    return (df["exchange"].isin(u["exchanges"])
            & (mcap >= u["min_market_cap_vnd"])
            & (_num(df, "avg_turnover_20d") >= u["min_avg_turnover_20d_vnd"])
            & (_num(df, "data_quality_score") >= u["min_data_quality_score"]))


def _co_lai(df, st, lens):
    # NULL quý lỗ = không kiểm được (thiếu BCTC quý) → KHÔNG cho qua; run() báo
    # riêng trong `unverifiable` để người đọc biết lý do, không lẫn với "có lỗ".
    ttm_ok = df["is_loss_making"].astype("boolean").fillna(True) == False  # noqa: E712
    return ttm_ok & (_num(df, "loss_quarters_12q_actual") == 0)


def _pe_toi_da(df, st, lens):
    pe = _num(df, "pe_current")
    return (pe > 0) & (pe <= st["max"])


def _so_graham(df, st, lens):
    return (_num(df, "pe_current") * _num(df, "pb_current")) <= st["max"]


def _co_tuc(df, st, lens):
    return _num(df, "dividend_years_consecutive") >= st["min_years"]


def _thanh_toan(df, st, lens):
    # Chỉ áp cho NONFIN: ngân hàng/bảo hiểm/chứng khoán không có hệ số này theo
    # nghĩa công nghiệp — đánh trượt là bịa kết luận tiêu cực (xem SKILL.md).
    return (df["com_class"] != "NONFIN") | (_num(df, "current_ratio") >= st["min"])


def _roe_ben(df, st, lens):
    return ((_num(df, "roe_avg_8q") >= st["min_roe"])
            & (_num(df, "roe_stability") >= st["min_stability"]))


def _tang_truong(df, st, lens):
    return ((_num(df, "earnings_cagr_3y") >= st["min_earnings_cagr"])
            & (_num(df, "revenue_cagr_3y") >= st["min_revenue_cagr"]))


def _deu_dan(df, st, lens):
    return _num(df, "growth_consistency") >= st["min"]


def _pe_tran(df, st, lens):
    pe = _num(df, "pe_current")
    return (pe > 0) & (pe <= st["max"])


_STEPS = {
    "vu_tru": _vu_tru, "co_lai": _co_lai, "pe_toi_da": _pe_toi_da,
    "so_graham": _so_graham, "co_tuc": _co_tuc, "thanh_toan": _thanh_toan,
    "bien_an_toan": _so_graham, "roe_ben": _roe_ben, "tang_truong": _tang_truong,
    "deu_dan": _deu_dan, "pe_tran": _pe_tran,
}


def _sort_pe_x_pb(df):
    return df.sort_values(["pe_x_pb", "symbol"], ascending=[True, True], kind="mergesort")


def _sort_quality_growth(df):
    out = df.assign(_qg=(_num(df, "quality_score") + _num(df, "growth_score")) / 2)
    out = out.sort_values(["_qg", "symbol"], ascending=[False, True], kind="mergesort")
    return out.drop(columns="_qg")


_SORTS = {"pe_x_pb_asc": _sort_pe_x_pb, "quality_growth_desc": _sort_quality_growth}


def run(df: pd.DataFrame, lens: str, cfg: dict) -> dict:
    """Chạy phễu. Trả {lens, label, config_version, steps, passed, waiting, unverifiable}."""
    lenses = cfg.get("lenses", {})
    if lens not in lenses:
        raise ValueError(f"Lăng kính lạ '{lens}'. Có: {sorted(lenses)}")
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise KeyError(f"Thiếu cột đầu vào cho phễu: {sorted(missing)}")
    spec = lenses[lens]

    cur = df.sort_values("symbol", kind="mergesort").reset_index(drop=True)
    cur = cur.assign(pe_x_pb=_num(cur, "pe_current") * _num(cur, "pb_current"))
    cur = cur.assign(price_to_graham=(cur["pe_x_pb"] / 22.5) ** 0.5)

    steps, unverifiable = [], []
    for st in spec["steps"]:
        mask = _STEPS[st["id"]](cur, st, spec).fillna(False).astype(bool)
        if st["id"] == "co_lai":
            unverifiable = sorted(cur.loc[~mask & cur["loss_quarters_12q_actual"].isna(),
                                          "symbol"].tolist())
        cur = cur[mask]
        steps.append({"id": st["id"], "label": st["label"], "remaining": int(len(cur))})

    cur = _SORTS[spec["sort"]](cur)
    cols = [c for c in OUTPUT_COLUMNS if c in cur.columns]
    is_wait = cur["risk_gate"] == WAIT_GATE
    return {
        "lens": lens,
        "label": spec.get("label", ""),
        "config_version": cfg["version"],
        "steps": steps,
        "passed": cur.loc[~is_wait, cols].reset_index(drop=True),
        "waiting": cur.loc[is_wait, cols].reset_index(drop=True),
        "unverifiable": unverifiable,
    }
