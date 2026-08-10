"""Tầng 1 kiểm chứng dữ liệu — chặn dữ liệu hỏng ngay tại ingestion.

Nguyên tắc: nguồn thiếu cột bắt buộc thì RAISE để job dừng và báo lỗi,
KHÔNG trả DataFrame rỗng âm thầm. Hành vi trả rỗng của code cũ đã che giấu
bug ánh xạ cột trong _normalize_company suốt nhiều tháng (industry_icb và
exchange NULL 100%) mà không ai biết.
"""
import pandas as pd


class SchemaError(RuntimeError):
    """Nguồn dữ liệu trả về thiếu cột bắt buộc."""


def assert_columns(df: pd.DataFrame, required: list[str], source: str) -> None:
    """Raise SchemaError nếu thiếu bất kỳ cột nào trong `required`."""
    actual = list(df.columns)
    missing = [c for c in required if c not in actual]
    if missing:
        raise SchemaError(
            f"[{source}] thiếu cột bắt buộc {missing}. Cột thật: {actual}"
        )


def filter_range(
    df: pd.DataFrame, column: str, low: float, high: float
) -> tuple[pd.DataFrame, int]:
    """Loại các dòng có `column` nằm ngoài [low, high].

    NULL/NaN được GIỮ LẠI — thiếu dữ liệu khác với dữ liệu sai.
    Trả về (df_còn_lại, số_dòng_bị_loại).
    """
    if df is None or df.empty or column not in df.columns:
        return df, 0
    values = pd.to_numeric(df[column], errors="coerce")
    keep = values.isna() | ((values >= low) & (values <= high))
    return df[keep].reset_index(drop=True), int((~keep).sum())


def status_for(rows_loaded: int, rows_rejected: int, threshold: float = 0.05) -> str:
    """Trạng thái cho etl_load_log: 'ok' | 'degraded' | 'empty'."""
    total = rows_loaded + rows_rejected
    if total == 0:
        return "empty"
    if rows_rejected / total > threshold:
        return "degraded"
    return "ok"
