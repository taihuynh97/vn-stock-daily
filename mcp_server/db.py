"""Kết nối read-only và rào chắn SQL cho MCP server.

Ba lớp bảo vệ độc lập:
  1. Kết nối read-only ở tầng DuckDB (nếu backend hỗ trợ).
  2. `enable_external_access=false` — chặn mọi hàm bảng đọc file/mạng của
     DuckDB (read_text, read_csv, glob, httpfs, ...). Rào chắn cú pháp ở
     (3) không bắt được các hàm này vì về mặt cú pháp chúng là SELECT hợp
     lệ; đây là lớp chặn đúng chỗ cho nhóm rủi ro này.
  3. Rào chắn cú pháp ở tầng ứng dụng — luôn áp dụng, kể cả khi (1)/(2)
     thất bại. Dùng chính parser của DuckDB (`duckdb.extract_statements`)
     cho statement-type, và chính PLAN của DuckDB (`EXPLAIN (FORMAT JSON)`)
     cho tên hàm bảng thật sự được gọi — KHÔNG tự viết regex đoán cú pháp
     SQL/tên hàm từ chuỗi ký tự thô. Xem lịch sử ở `assert_safe_sql`.
"""
import json
import os
from pathlib import Path

import duckdb

# Danh sách ĐÓNG, HỮU HẠN các tên hàm bảng công khai có side-effect quản trị
# — đã tra `duckdb_functions()` trên md:vn_market thật (where function_type=
# 'table'), lọc theo has_side_effects=true và theo tên gợi ý quản trị
# (checkpoint/vacuum/force/flush/write): chỉ 2 cái ngoài phạm vi đọc dữ
# liệu — `checkpoint()` (flush WAL ra đĩa) và `force_checkpoint()` (cùng
# họ, ép checkpoint bỏ qua điều kiện threshold).
_DANGEROUS_TABLE_FUNCTIONS = {"checkpoint", "force_checkpoint"}


def _called_table_functions(con, query: str) -> set[str]:
    """Tên (viết hoa) của mọi table-function THẬT SỰ xuất hiện trong physical
    plan của `query`, đã qua resolve/chuẩn hoá của chính DuckDB — miễn nhiễm
    với cách viết gốc (dấu ngoặc kép quanh tên, comment chen giữa, qualify
    schema, khoảng trắng thừa...) vì ta đọc plan đã biên dịch xong, không
    phải chuỗi ký tự do người gọi kiểm soát.

    Không thực thi `query` — `EXPLAIN` chỉ sinh plan, không chạy. Đã tự xác
    minh bằng SEQUENCE: `nextval('seq')` không tăng sau khi bị `EXPLAIN`,
    kể cả `EXPLAIN (FORMAT JSON)`, trong khi `execute()` bình thường thì
    tăng đúng — an toàn để dùng cả với hàm có side-effect thật.

    Dùng `FORMAT JSON` thay vì text ASCII-art mặc định của `EXPLAIN`: với
    tên hàm dài (`FORCE_CHECKPOINT`, hầu hết `__MD_*`), text mặc định ngắt
    dòng bên trong khung vẽ ASCII khi tên không vừa một dòng — khi đó nhãn
    "Function:" nằm tách trên một dòng riêng, cách tên hàm bởi ký tự khung
    vẽ (không phải khoảng trắng), nên bất kỳ regex quét text nào theo mẫu
    "Function:\\s*(tên)" đều đọc nhầm ký tự khung vẽ thành "tên hàm" và bỏ
    lọt — đã tự tái tạo bằng thực nghiệm: xảy ra với chính `force_checkpoint`,
    một trong hai hàm mà lớp chặn này phải bắt được. JSON không có khái
    niệm "khung vẽ vừa dòng" nên không có lớp lỗi này.

    Chỉ hàm bảng (xuất hiện trong `FROM`) mới sinh node "Function" trong
    plan — hàm scalar dùng trong SELECT list (`replace(...)`) không sinh
    node kiểu này (nó là một biểu thức trong PROJECTION, không phải một
    node quét riêng), nên không cần allowlist cho `replace` như các vòng
    sửa trước — đã tự xác minh thực nghiệm cả dạng trần lẫn bọc ngoặc.
    """
    plan_rows = con.execute(f"EXPLAIN (FORMAT JSON) {query}").fetchall()
    names: set[str] = set()
    for _label, plan_json in plan_rows:
        try:
            nodes = json.loads(plan_json)
        except (json.JSONDecodeError, TypeError):
            continue

        def walk(items):
            for node in items:
                if not isinstance(node, dict):
                    continue
                func = node.get("extra_info", {}).get("Function")
                if func:
                    names.add(str(func).upper())
                walk(node.get("children", []))

        walk(nodes)
    return names


class SqlGuardError(RuntimeError):
    """Câu lệnh SQL bị từ chối vì không phải truy vấn đọc."""


def assert_safe_sql(con, query: str) -> None:
    """Chỉ cho phép đúng một câu SELECT duy nhất, không gọi hàm bảng nguy
    hiểm (dù viết theo cách nào).

    Cần `con` (khác vòng sửa trước) vì bước cuối dùng `EXPLAIN` — cần một
    connection thật để DuckDB resolve/bind hàm trong catalog, đặc biệt
    quan trọng với hàm chỉ tồn tại trên MotherDuck (`__MD_*`) — không thể
    resolve nếu không có connection thật tới `md:`.

    Dùng chính parser của DuckDB (`duckdb.extract_statements`) cho statement
    type, và chính plan của DuckDB (`EXPLAIN`) cho tên hàm — thay vì tự dò
    bằng regex. Lịch sử bốn vòng trước đó, mỗi vòng bỏ sót một lớp khác
    nhau, tất cả đều là hệ quả của việc tự đoán cấu trúc câu lệnh/tên hàm
    từ chuỗi ký tự thô thay vì hỏi thẳng DuckDB:
      - Vòng 1: quét toàn bộ từ trong câu — chặn nhầm tên hàm/tên cột trùng
        từ khoá cấm (`replace(...)`, cột tên `update`).
      - Vòng 2: sau khi thu hẹp theo vị trí — bỏ sót `checkpoint()` gọi như
        hàm, và thứ tự strip comment/string sai khiến `--` trong chuỗi
        `'--'` nuốt luôn `;` và lệnh ghi phía sau.
      - Vòng 3: allowlist tên hàm chỉ áp cho một nhánh regex nên
        `(replace(...))` bọc thêm ngoặc lại bị chặn nhầm; và cú pháp trích
        dẫn `$$...$$` / `E'...'` của DuckDB không được regex string-literal
        nhận diện. → Chuyển statement-type sang `duckdb.extract_statements`
        (chính parser DuckDB), nhưng vẫn giữ regex `_CALL_PATTERN`/
        `_INTERNAL_FUNC_PATTERN` để đoán TÊN HÀM đang được gọi từ chuỗi thô.
      - Vòng 4 (dẫn tới lần viết lại này): chính hai regex đoán-tên-hàm đó
        bị vượt qua bằng `"checkpoint"()` (quote), `checkpoint/**/()`
        (comment chen giữa), `main."checkpoint"()` (qualify schema) — vì
        "đoán TÊN HÀM đang được gọi" là CÙNG một lớp vấn đề với "đoán cấu
        trúc câu lệnh", cần CÙNG một loại giải pháp: hỏi thẳng DuckDB thay
        vì đoán từ text. `EXPLAIN` cho tên hàm đã resolve xong, miễn nhiễm
        với mọi cách viết — xem `_called_table_functions`.
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
    # Dùng statements[0].query (văn bản ĐÃ ĐƯỢC DUCKDB VIẾT LẠI), không phải
    # `query` gốc của người gọi — cho `EXPLAIN`. Cú pháp PRAGMA rút gọn
    # (`PRAGMA database_list`) tuy có statement.type=SELECT nhưng bản thân
    # `EXPLAIN PRAGMA database_list` bị DuckDB từ chối ("PRAGMA function does
    # not have a function specified") vì EXPLAIN không hiểu cú pháp PRAGMA
    # thô; `statements[0].query` cho dạng đã viết lại
    # (`SELECT * FROM pragma_database_list();`), EXPLAIN được bình thường.
    # Với mọi câu SELECT thường (không phải PRAGMA), `.query` giống hệt văn
    # bản gốc nên không đổi hành vi chặn các biến thể quote/comment/qualify.
    try:
        called = _called_table_functions(con, statements[0].query)
    except duckdb.Error as e:
        raise SqlGuardError(f"Không phân tích được kế hoạch truy vấn: {e}") from e
    dangerous = {
        f for f in called
        if f.lower() in _DANGEROUS_TABLE_FUNCTIONS or f.startswith("__")
    }
    if dangerous:
        raise SqlGuardError(
            f"Câu lệnh gọi hàm quản trị/nội bộ bị cấm: {sorted(dangerous)}"
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
    assert_safe_sql(con, sql)
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
