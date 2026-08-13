"""Áp hồ sơ chấm điểm (profile) lên mart_stock_scorecard.

Đây là bản cài đặt DUY NHẤT của logic điểm tổng hợp — cả MCP server lẫn job
báo cáo định kỳ đều import module này, nên hai luồng không bao giờ lệch nhau.

Vì sao điểm tổng hợp không nằm trong dbt: đổi trọng số là việc sẽ làm rất
nhiều lần khi dò gu đầu tư. Tính lúc đọc thì mất vài giây, còn tính trong
dbt thì phải chạy lại toàn bộ mart.
"""
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE_PATH = ROOT / "config" / "scoring_profiles.yml"

COMPONENTS = ["value", "quality", "growth", "dividend", "safety"]

# Mọi khoá mà apply_universe() THẬT SỰ đọc. Khoá nào không có ở đây thì không
# code nào áp — và một khoá cấu hình im lặng không làm gì là loại lỗi tệ nhất
# trong file này: người dùng đặt ngưỡng, tin rằng đã lọc, mà không lọc gì.
# Bản kế hoạch gốc từng có `min_quarters_history` ở đúng tình trạng đó.
KNOWN_UNIVERSE_KEYS = {
    "exchanges", "min_market_cap_vnd", "min_avg_turnover_20d_vnd",
    "min_data_quality_score", "min_quarters_history",
}
KNOWN_REQUIRE_KEYS = {
    "dividend_years_min", "roe_avg_8q_min", "exclude_loss_making",
}


def load_profiles(path=None) -> dict:
    """Đọc scoring_profiles.yml, hợp nhất universe_defaults vào từng profile.

    Ném lỗi nếu gặp khoá lạ, hoặc trọng số không tổng bằng 1 — thà nổ lúc nạp
    cấu hình còn hơn im lặng cho ra một bảng xếp hạng sai.
    """
    path = Path(path) if path else DEFAULT_PROFILE_PATH
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    defaults = cfg.get("universe_defaults", {}) or {}
    for name, prof in cfg.get("profiles", {}).items():
        merged = dict(defaults)
        merged.update(prof.get("universe", {}) or {})
        prof["universe"] = merged
        prof.setdefault("require", {})

        unknown_uni = set(merged) - KNOWN_UNIVERSE_KEYS
        if unknown_uni:
            raise ValueError(
                f"Profile '{name}': khoá universe không được áp dụng: "
                f"{sorted(unknown_uni)}. Khoá hợp lệ: {sorted(KNOWN_UNIVERSE_KEYS)}"
            )
        unknown_req = set(prof["require"]) - KNOWN_REQUIRE_KEYS
        if unknown_req:
            raise ValueError(
                f"Profile '{name}': khoá require không được áp dụng: "
                f"{sorted(unknown_req)}. Khoá hợp lệ: {sorted(KNOWN_REQUIRE_KEYS)}"
            )
        unknown_w = set(prof.get("weights", {})) - set(COMPONENTS)
        if unknown_w:
            raise ValueError(
                f"Profile '{name}': thành phần điểm không tồn tại: {sorted(unknown_w)}"
            )
        total = sum(prof.get("weights", {}).values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"Profile '{name}': tổng trọng số = {total}, phải bằng 1,0"
            )
    return cfg


def get_profile(profile_name: str = None, path=None) -> dict:
    cfg = load_profiles(path)
    name = profile_name or cfg.get("default_profile")
    profiles = cfg.get("profiles", {})
    if name not in profiles:
        raise KeyError(f"Không có profile '{name}'. Có: {sorted(profiles)}")
    prof = dict(profiles[name])
    prof["name"] = name
    return prof


def compute_composite(df: pd.DataFrame, profile: dict) -> pd.DataFrame:
    """Thêm cột composite_score và components_missing.

    Thành phần NULL mà profile gán trọng số > 0 → composite_score = NaN và
    mã bị liệt kê là "không chấm được". KHÔNG coi NULL là 0 điểm: 0 nghĩa là
    "kém nhất nhóm", NULL nghĩa là "không đo được" — trộn hai thứ này là sai.
    """
    out = df.copy()
    weights = profile["weights"]
    required = [c for c in COMPONENTS if weights.get(c, 0) > 0]

    missing = out[[f"{c}_score" for c in required]].isna()
    out["components_missing"] = [
        ",".join(c for c, m in zip(required, row) if m)
        for row in missing.itertuples(index=False)
    ]

    total = pd.Series(0.0, index=out.index)
    for comp in COMPONENTS:
        w = weights.get(comp, 0)
        if w:
            total = total + out[f"{comp}_score"].astype(float) * w
    out["composite_score"] = total.where(out["components_missing"] == "")
    return out


def apply_universe(df: pd.DataFrame, profile: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Tách thành (đủ điều kiện, bị loại kèm lý do).

    Một mã có thể trượt NHIỀU điều kiện cùng lúc — đo thực tế trên production:
    85,5%-96,4% mã bị loại trượt từ 2 điều kiện trở lên. `reject_reason` liệt
    kê ĐẦY ĐỦ mọi điều kiện trượt của mã đó, nối bằng "; ", không chỉ điều
    kiện đầu tiên gặp phải — để trả lời đúng câu hỏi "vì sao mã X bị loại" mà
    không bỏ sót lý do (bản trước chỉ giữ lý do đầu, khiến ví dụ một mã trượt
    cả sàn lẫn vốn hoá chỉ hiện "ngoài sàn cho phép").
    """
    uni = profile["universe"]
    req = profile.get("require", {}) or {}
    out = df.copy()

    # Danh sách (mask, lý do) — KHÔNG áp dụng tuần tự loại trừ lẫn nhau, mỗi
    # check độc lập chạy trên toàn bộ out để một mã có thể khớp nhiều check.
    checks: list[tuple[pd.Series, str]] = []
    if uni.get("exchanges"):
        checks.append((~out["exchange"].isin(uni["exchanges"]), "ngoài sàn cho phép"))
    if uni.get("min_market_cap_vnd") is not None:
        checks.append((out["market_cap"].fillna(0) < uni["min_market_cap_vnd"],
                        "vốn hoá dưới ngưỡng"))
    if uni.get("min_avg_turnover_20d_vnd") is not None:
        checks.append((out["avg_turnover_20d"].fillna(0) < uni["min_avg_turnover_20d_vnd"],
                        "thanh khoản dưới ngưỡng"))
    if uni.get("min_data_quality_score") is not None:
        checks.append((out["data_quality_score"].fillna(0) < uni["min_data_quality_score"],
                        "chất lượng dữ liệu thấp"))
    if uni.get("min_quarters_history") is not None:
        # Khác với min_data_quality_score: điểm dữ liệu là tổ hợp 5 thành phần,
        # một mã có thể đạt 60 điểm nhờ giá và độ tươi trong khi lịch sử tỷ số
        # vẫn mỏng. Hai ngưỡng đo hai thứ khác nhau.
        checks.append((out["quarters_available"].fillna(0) < uni["min_quarters_history"],
                        "lịch sử tỷ số chưa đủ số quý"))
    if req.get("dividend_years_min") is not None:
        checks.append((out["dividend_years_consecutive"].fillna(0) < req["dividend_years_min"],
                        "cổ tức chưa đủ số năm liên tiếp"))
    if req.get("roe_avg_8q_min") is not None:
        checks.append((out["roe_avg_8q"].fillna(-1) < req["roe_avg_8q_min"],
                        "ROE trung bình 8 quý dưới ngưỡng"))
    if req.get("exclude_loss_making"):
        # Quy ước xuyên suốt hàm này: THIẾU DỮ LIỆU THÌ TRƯỢT điều kiện, không
        # phải mặc định cho qua — các check khác đạt điều đó bằng fillna(0)
        # hoặc fillna(-1) trên một ngưỡng "nhỏ hơn thì trượt". is_loss_making
        # là boolean thẳng nên phải fillna(True) (không biết có lỗ hay không
        # → coi như có lỗ, loại), KHÔNG phải fillna(False) (không biết → coi
        # như không lỗ, cho qua) — chiều ngược sẽ đi ngược đúng quy ước trên.
        checks.append((out["is_loss_making"].fillna(True).astype(bool), "đang lỗ"))

    n = len(out)
    reason_lists: list[list[str]] = [[] for _ in range(n)]
    for mask, text in checks:
        for pos in mask.to_numpy().nonzero()[0]:
            reason_lists[pos].append(text)

    reject_reason = pd.Series(["; ".join(r) for r in reason_lists], index=out.index)
    is_rejected = reject_reason != ""
    ok = out[~is_rejected].reset_index(drop=True)
    rejected = out[is_rejected].copy()
    rejected["reject_reason"] = reject_reason[is_rejected].values
    return ok, rejected.reset_index(drop=True)


SCORECARD_SQL = "SELECT * FROM mart_stock_scorecard"


def screen(con, profile_name: str = None, limit: int = 30,
           profile_path=None) -> pd.DataFrame:
    """Chạy screener: đọc mart → lọc universe → tính điểm tổng hợp → xếp hạng."""
    profile = get_profile(profile_name, profile_path)
    df = con.execute(SCORECARD_SQL).df()
    ok, _ = apply_universe(df, profile)
    scored = compute_composite(ok, profile)
    ranked = scored.dropna(subset=["composite_score"]).sort_values(
        "composite_score", ascending=False
    )
    ranked.insert(0, "rank", range(1, len(ranked) + 1))
    ranked["profile"] = profile["name"]
    return ranked.head(limit).reset_index(drop=True)


def screen_report(con, profile_name: str = None, limit: int = 30,
                  profile_path=None) -> dict:
    """Như screen() nhưng trả thêm phần bị loại — để giải thích, không giấu.

    `rejected_counts`: số mã trượt TỪNG điều kiện riêng lẻ, CHO PHÉP CHỒNG LẤP
    — một mã trượt cả sàn lẫn vốn hoá được cộng vào cả hai khoá. Vì vậy
    `sum(rejected_counts.values())` lớn hơn số mã bị loại thật (đo thực tế:
    85,5%-96,4% mã bị loại trượt ≥2 điều kiện). `rejected_total` là số mã bị
    loại thật — dùng khoá này để đối chiếu, không tự cộng `rejected_counts`
    lại rồi tưởng đó là tổng số mã.
    """
    profile = get_profile(profile_name, profile_path)
    df = con.execute(SCORECARD_SQL).df()
    ok, rejected = apply_universe(df, profile)
    scored = compute_composite(ok, profile)
    unscored = scored[scored["composite_score"].isna()]
    ranked = scored.dropna(subset=["composite_score"]).sort_values(
        "composite_score", ascending=False
    ).head(limit).reset_index(drop=True)
    ranked.insert(0, "rank", range(1, len(ranked) + 1))

    if len(rejected):
        reasons_flat = rejected["reject_reason"].str.split("; ").explode()
        rejected_counts = reasons_flat.value_counts().to_dict()
    else:
        rejected_counts = {}

    return {
        "profile": profile["name"],
        "label": profile.get("label", ""),
        "ranked": ranked,
        "unscored": unscored[["symbol", "components_missing"]].reset_index(drop=True),
        "rejected_counts": rejected_counts,
        "rejected_total": len(rejected),
        "universe_size": len(ok),
    }
