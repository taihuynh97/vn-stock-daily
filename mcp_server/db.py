"""Kết nối read-only và rào chắn SQL cho MCP server.

Ba lớp bảo vệ độc lập:
  1. Kết nối read-only ở tầng DuckDB (nếu backend hỗ trợ).
  2. `enable_external_access=false` — chặn mọi hàm bảng đọc file/mạng của
     DuckDB (read_text, read_csv, glob, httpfs, ...). Rào chắn cú pháp ở
     (3) không bắt được các hàm này vì về mặt cú pháp chúng là SELECT hợp
     lệ; đây là lớp chặn đúng chỗ cho nhóm rủi ro này.
  3. Rào chắn cú pháp ở tầng ứng dụng — luôn áp dụng, kể cả khi (1)/(2)
     thất bại. Dùng chính parser của DuckDB (`duckdb.extract_statements`),
     KHÔNG tự viết regex mô phỏng lexer SQL — xem lịch sử ở assert_safe_sql.
"""
import os
from pathlib import Path

import duckdb


class SqlGuardError(RuntimeError):
    """Câu lệnh SQL bị từ chối vì không phải truy vấn đọc."""


def assert_safe_sql(query: str) -> None:
    """Chỉ cho phép đúng một câu SELECT duy nhất.

    Dùng chính parser của DuckDB (`duckdb.extract_statements`) thay vì tự
    dò bằng regex. Lịch sử ba vòng regex trước đó, mỗi vòng bỏ sót một lớp
    cú pháp khác nhau:
      - Vòng 1: quét toàn bộ từ trong câu — chặn nhầm tên hàm/tên cột trùng
        từ khoá cấm (`replace(...)`, cột tên `update`).
      - Vòng 2: sau khi thu hẹp theo vị trí — bỏ sót `checkpoint()` gọi như
        hàm, và thứ tự strip comment/string sai khiến `--` trong chuỗi
        `'--'` nuốt luôn `;` và lệnh ghi phía sau.
      - Vòng 3 (phát hiện dẫn tới lần viết lại này): allowlist tên hàm chỉ
        áp cho một nhánh regex nên `(replace(...))` bọc thêm ngoặc lại bị
        chặn nhầm; và cú pháp trích dẫn `$$...$$` / `E'...'` của DuckDB
        không được regex string-literal nhận diện, cho `; drop table t`
        lọt qua dưới dạng "bên trong chuỗi".
    `duckdb.extract_statements` hiểu đúng MỌI cú pháp trích dẫn DuckDB hỗ
    trợ vì nó CHÍNH LÀ DuckDB, không phải một xấp xỉ của DuckDB — không thể
    bỏ sót một lớp cú pháp thứ tư theo kiểu trên.

    Lưu ý đã biết (không phải hồi quy, xem task-1-report.md mục "Vòng sửa
    3"): `select * from checkpoint()` được parser phân loại type=SELECT
    (checkpoint() chỉ là một table function trong mệnh đề FROM, giống
    read_csv(...)) nên vẫn "qua" được whitelist này. Không có lớp regex
    nào vá được việc này một cách đáng tin cậy hơn — xem báo cáo.
    """
    if not query or not query.strip():
        raise SqlGuardError("Câu truy vấn rỗng.")
    try:
        statements = duckdb.extract_statements(query)
    except duckdb.Error as e:
        raise SqlGuardError(f"Không phân tích được câu lệnh: {e}") from e
    if len(statements) != 1:
        raise SqlGuardError(
            f"Chỉ cho phép đúng một câu lệnh, tìm thấy {len(statements)}."
        )
    if statements[0].type != duckdb.StatementType.SELECT:
        raise SqlGuardError(
            f"Chỉ chấp nhận câu lệnh SELECT, nhận được {statements[0].type}."
        )


def get_readonly_conn():
    """Trả (connection, is_readonly).

    MotherDuck có thể không nhận read_only — khi đó vẫn kết nối được nhưng
    is_readonly=False, và rào chắn SQL ở tầng ứng dụng là lớp bảo vệ duy nhất.

    Cả hai nhánh đều tắt enable_external_access ngay sau khi connect (không
    được truyền qua config= lúc connect — làm MotherDuck lỗi khi nạp
    extension). Đây là chặn đọc file/mạng (read_text, read_csv, glob,
    httpfs, ...) — độc lập với rào chắn từ khoá ghi ở assert_safe_sql.
    """
    root = Path(__file__).resolve().parent.parent
    dbpath = os.getenv("WAREHOUSE_DB", str(root / "data" / "warehouse.duckdb"))
    try:
        con = duckdb.connect(dbpath, read_only=True)
        is_readonly = True
    except Exception:
        con = duckdb.connect(dbpath)
        is_readonly = False
    con.execute("SET enable_external_access=false")
    return con, is_readonly


def run_query(con, sql: str, params=None, limit: int = 1000) -> list[dict]:
    """Chạy truy vấn đọc, trả tối đa `limit` dòng dưới dạng list[dict]."""
    assert_safe_sql(sql)
    wrapped = f"SELECT * FROM ({sql.rstrip().rstrip(';')}) LIMIT {int(limit)}"
    df = con.execute(wrapped, params or []).df()
    return df.to_dict(orient="records")


def as_of(con) -> dict:
    """Thời điểm dữ liệu — mọi tool phải trả kèm để agent không nói về số cũ."""
    price = con.execute(
        "SELECT max(trade_date) FROM fct_price_daily"
    ).fetchone()[0]
    ratio = con.execute(
        "SELECT max(period_end_date) FROM fct_financial_quarterly"
    ).fetchone()[0]
    return {
        "price_as_of": str(price) if price else None,
        "ratio_as_of": str(ratio) if ratio else None,
        "warehouse": os.getenv("WAREHOUSE_DB", "data/warehouse.duckdb"),
    }
