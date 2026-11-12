"""Vietcap (iq.vietcap.com.vn): báo cáo tài chính chi tiết (KQKD, CĐKT, LCTT).

Một mã có hai endpoint:
- /v1/company/{mã}/financial-statement?section=... → {"years": [...], "quarters": [...]},
  mỗi phần tử là một kỳ, trường số liệu dạng isa1, bsa12, cfa3...
- /v1/company/{mã}/financial-statement/metrics → tên chỉ tiêu (Việt/Anh) theo
  từng mục, dùng chung cho cả ba báo cáo nên cache theo mã.

Đầu ra giữ đúng hợp đồng ingest_market đã đọc từ vnstock 4.0.9: cột
`item, item_en, item_id, <kỳ…>`; dòng theo thứ tự trường trong phản hồi (row_seq
của warehouse dựa vào thứ tự này); kỳ mới nhất trước, giữ MAX_PERIODS kỳ.
"""
from __future__ import annotations

import re
import unicodedata

import pandas as pd

from .http import SourceError, iq_data

SECTIONS = {"income_statement": "INCOME_STATEMENT", "balance_sheet": "BALANCE_SHEET",
            "cash_flow": "CASH_FLOW"}
# vnstock gói cộng đồng (vnai) chỉ trả 8 kỳ gần nhất; nguồn có nhiều hơn (~35
# quý). Giữ 8 để khối lượng nạp và dữ liệu warehouse không đổi; muốn nạp sâu
# hơn thì nâng số này có chủ đích.
MAX_PERIODS = 8

_metrics_cache: dict[str, dict[str, tuple]] = {}


def clear_cache() -> None:
    _metrics_cache.clear()


def item_id(title_en) -> str:
    """Định danh snake_case từ tên tiếng Anh của chỉ tiêu (khớp item_id cũ).

    Bỏ số thứ tự đầu dòng ("1.", "1.2.", "IV.", "A."), bỏ dấu, chữ thường,
    "&" → "and", bỏ nháy, ký tự khác chữ/số → "_", gộp "_" liên tiếp; bắt đầu
    bằng số thì thêm "n_"."""
    if not isinstance(title_en, str) or not title_en.strip():
        return title_en
    s = unicodedata.normalize("NFKD", title_en).encode("ascii", "ignore").decode("ascii")
    for pattern in (r"^\d+(\.\d+)*\.\s*", r"^[IVXivx]+(\.\d+)*\.\s*", r"^[A-Za-z]\.\s*"):
        s = re.sub(pattern, "", s)
    s = s.lower()
    s = re.sub(r"\s*&\s*", " and ", s)
    s = re.sub(r"['\"`]", "", s)
    s = re.sub(r"[^a-z0-9\s_-]", " ", s)
    s = re.sub(r"[\s\-/\\]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    if s and s[0].isdigit():
        s = "n_" + s
    if not s:
        s = re.sub(r"[^a-zA-Z0-9]", "", title_en).lower()[:20]
    return s


def _metrics(symbol: str) -> dict[str, tuple]:
    """field → (tên Việt, tên Anh), gộp mọi mục (trùng field thì mục sau thắng)."""
    if symbol not in _metrics_cache:
        data = iq_data(f"/v1/company/{symbol}/financial-statement/metrics")
        if not isinstance(data, dict):
            raise SourceError(f"metrics {symbol}: phản hồi không phải object")
        names = {}
        for items in data.values():
            for it in items or []:
                if isinstance(it, dict) and it.get("field"):
                    names[it["field"]] = (it.get("titleVi"), it.get("titleEn"))
        _metrics_cache[symbol] = names
    return _metrics_cache[symbol]


def _label(rec: dict, period: str) -> str:
    y, q = int(rec["yearReport"]), int(rec["lengthReport"])
    return f"{y}-Q{q}" if period == "quarter" and q < 5 else str(y)


def _sort_key(label: str) -> tuple:
    if "-Q" in label:
        y, q = label.split("-Q")
        return int(y), int(q)
    return int(label), 5


def statement(symbol: str, statement_type: str, period: str) -> pd.DataFrame:
    """Một báo cáo dạng rộng: [item, item_en, item_id, <kỳ mới nhất…>].

    Ô trống của nguồn thành 0 và bỏ kỳ toàn 0 (như vnstock; dbt coi 0 tuyệt
    đối là ô trống). Không có kỳ nào → DataFrame rỗng."""
    if statement_type not in SECTIONS:
        raise ValueError(f"statement_type không hợp lệ: {statement_type}")
    data = iq_data(f"/v1/company/{symbol}/financial-statement",
                   {"section": SECTIONS[statement_type]})
    if data is None:
        return pd.DataFrame()
    if not isinstance(data, dict):
        raise SourceError(f"financial-statement {symbol}: phản hồi không phải object")
    records = data.get("years" if period == "year" else "quarters") or []
    if not records:
        return pd.DataFrame()
    names = _metrics(symbol)

    fields: list[str] = []          # thứ tự trường như phản hồi (gộp, giữ lần đầu thấy)
    seen = set()
    for rec in records:
        for k in rec:
            if k in names and k not in seen:
                seen.add(k)
                fields.append(k)

    columns = {}
    for rec in records:
        columns[_label(rec, period)] = [rec.get(f) for f in fields]
    wide = pd.DataFrame(columns, index=fields).apply(pd.to_numeric, errors="coerce").fillna(0)
    wide = wide.loc[:, (wide != 0).any(axis=0)]
    keep = sorted(wide.columns, key=_sort_key, reverse=True)[:MAX_PERIODS]

    out = pd.DataFrame({
        "item": [names[f][0] for f in fields],
        "item_en": [names[f][1] for f in fields],
        "item_id": [item_id(names[f][1]) for f in fields],
    })
    for col in keep:
        out[col] = wide[col].to_numpy()
    return out
