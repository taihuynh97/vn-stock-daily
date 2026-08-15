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
     cho tên TABLE-FUNCTION thật sự được gọi (đối chiếu ALLOWLIST, không
     phải blocklist — xem `_ALLOWED_TABLE_FUNCTIONS`) — KHÔNG tự viết regex
     đoán cú pháp SQL/tên hàm từ chuỗi ký tự thô. Xem lịch sử ở
     `assert_safe_sql`.

GIỚI HẠN ĐÃ BIẾT, CHƯA GIẢI QUYẾT (vòng sửa 5, xem task-1-report.md): lớp
(3) chỉ kiểm TABLE-FUNCTION (hàm xuất hiện trong mệnh đề FROM, sinh node
"Function" riêng trong physical plan). HÀM SCALAR (dùng trong SELECT list,
vd `some_dangerous_scalar_fn(...)`) — nếu có alias (`AS bất_kỳ_tên_gì`,
cực kỳ phổ biến trong SQL thật) — bị DuckDB ẩn hoàn toàn khỏi output
`EXPLAIN` (kể cả `explain_output='ALL'`, ở mọi giai đoạn plan: logical,
logical_opt, physical): trường "Projections"/"Expressions" chỉ hiển thị
TÊN ALIAS, không hiển thị biểu thức gốc. Đã tự kiểm thực nghiệm — không có
cách nào qua `EXPLAIN` hay API Python hiện có của `duckdb` (đã thử cả
`duckdb_dependencies()` sau `PREPARE`, không track lời gọi hàm ad-hoc) để
lấy lại tên hàm scalar một khi đã bị alias che. Nghĩa là hàm scalar có
side-effect thật trên MotherDuck (vd `MD_INTERRUPT_SERVER_CONNECTION`,
`write_log`, `set_bit`) KHÔNG bị lớp (3) chặn nếu được gọi kèm alias —
residual risk thật, đã báo cáo, chưa có giải pháp trong phạm vi cơ chế
EXPLAIN-based này.
"""
import json
import os
from pathlib import Path

import duckdb

# ALLOWLIST — không phải blocklist. Vòng sửa 4 dùng blocklist
# (_DANGEROUS_TABLE_FUNCTIONS + tiền tố "__") và bị vượt qua: quét
# `duckdb_functions()` trên md:vn_market thật cho thấy 193 table-function,
# blocklist cũ chỉ chặn 12 — 181 hàm lọt qua, gồm 52 hàm họ `MD_*` KHÔNG
# dùng tiền tố "__" (vd `MD_DROP_DATABASE`, `MD_CREATE_FLIGHT` — mô tả
# catalog: "chạy mã tuỳ ý theo lịch cron") và
# `json_execute_serialized_sql` (nhận một plan SQL đã serialize làm tham
# số — có thể giấu một lời gọi checkpoint()/hàm nguy hiểm khác BÊN TRONG
# tham số, EXPLAIN câu ngoài không thấy được vì plan trong chưa deserialize
# tại thời điểm EXPLAIN).
#
# Bài học sau 3 lần liên tiếp blocklist bị vượt qua (vòng 2: quên
# force_checkpoint dạng gọi hàm; vòng 3: quên toàn bộ họ MD_* không có
# tiền tố __; vòng 4 → giờ: quên hàm nhận SQL lồng làm tham số): liệt kê
# CÁI GÌ NGUY HIỂM không bao giờ đủ vì catalog MotherDuck ngoài tầm kiểm
# soát, có thể thêm hàm mới bất cứ lúc nào. Đảo lại: liệt kê CÁI GÌ ĐƯỢC
# PHÉP — mặc định chặn mọi thứ không nằm trong danh sách, không cần biết
# trước tên hàm nguy hiểm là gì. Đã xác nhận: toàn bộ trường hợp
# MUST_ALLOW tích luỹ qua các vòng (4 pragma đọc thông tin) chỉ cần đúng
# 5 hàm bảng đầu tiên bên dưới; 4 hàm còn lại là tiện ích phân tích thuần,
# không side-effect, dự phòng cho SQL tự do (Task 2/3 hoặc agent tự viết).
_ALLOWED_TABLE_FUNCTIONS = {
    "duckdb_databases", "duckdb_tables", "duckdb_views",
    "pragma_table_info", "pragma_version",
    "range", "generate_series", "unnest", "repeat",
}


def _called_table_functions(con, query: str, params=None) -> set[str]:
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

    `params` (Task 2): câu có placeholder `?` (vd `WHERE symbol = ?`, dùng
    trong `get_stock_profile`) khiến `EXPLAIN` tự nó ném
    "Values were not provided for the following prepared statement
    parameters" nếu không bind giá trị — DuckDB cần giá trị thật để
    resolve kiểu/lập kế hoạch, kể cả khi chỉ EXPLAIN chứ không chạy. Bind
    cùng `params` truyền cho `run_query`/`con.execute` thật, không phải
    giá trị giả — nếu không, một điều kiện lọc theo giá trị tham số (hiếm
    nhưng có thể xảy ra qua CASE/kiểu dữ liệu phụ thuộc giá trị) có thể
    làm plan EXPLAIN khác plan thật sự chạy. Đã tự xác minh thực nghiệm:
    `EXPLAIN` không thực thi câu lệnh (xem đoạn SEQUENCE ở trên) nên bind
    giá trị thật ở đây an toàn, không có side-effect.
    """
    plan_rows = con.execute(f"EXPLAIN (FORMAT JSON) {query}", params or []).fetchall()
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


def assert_safe_sql(con, query: str, params=None) -> None:
    """Chỉ cho phép đúng một câu SELECT duy nhất, không gọi hàm bảng nguy
    hiểm (dù viết theo cách nào).

    `params`: giá trị bind cho placeholder `?` trong `query` (nếu có) — cần
    truyền xuống `_called_table_functions` để bước `EXPLAIN` không ném lỗi
    "thiếu giá trị tham số". Mọi lời gọi hiện có (không dùng placeholder)
    không cần đổi, mặc định `None` tương đương `[]`.

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
      - Vòng 4: chính hai regex đoán-tên-hàm đó bị vượt qua bằng
        `"checkpoint"()` (quote), `checkpoint/**/()` (comment chen giữa),
        `main."checkpoint"()` (qualify schema) — vì "đoán TÊN HÀM đang được
        gọi" là CÙNG một lớp vấn đề với "đoán cấu trúc câu lệnh", cần CÙNG
        một loại giải pháp: hỏi thẳng DuckDB thay vì đoán từ text. Chuyển
        sang dùng `EXPLAIN` để lấy tên hàm đã resolve xong — nhưng vẫn là
        BLOCKLIST (`_DANGEROUS_TABLE_FUNCTIONS` + tiền tố `__`).
      - Vòng 5 (dẫn tới thiết kế hiện tại): blocklist tên hàm — dù đã đọc
        đúng tên từ EXPLAIN — vẫn là blocklist, và catalog MotherDuck có
        193 table-function, blocklist cũ chỉ chặn 12; 52 hàm họ `MD_*`
        không dùng tiền tố `__` (vd `MD_DROP_DATABASE`) và
        `json_execute_serialized_sql` (giấu một plan SQL khác — kể cả
        checkpoint() — làm tham số, EXPLAIN câu ngoài không thấy plan
        trong vì nó chưa deserialize) đều lọt qua. Đảo hẳn thành ALLOWLIST
        (`_ALLOWED_TABLE_FUNCTIONS`) — mặc định chặn mọi table-function
        không nằm trong danh sách cho phép, không cần biết trước tên hàm
        nguy hiểm là gì, không thể bị "quên liệt kê" một hàm mới.
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
    # thô; `statements[0].query` cho dạng đã viết lại (vd với
    # "PRAGMA database_list" là `SELECT * FROM duckdb_databases();` — DuckDB
    # rewrite thẳng ra bảng hệ thống, không phải qua một hàm tên
    # "pragma_database_list"), EXPLAIN được bình thường. Với mọi câu SELECT
    # thường (không phải PRAGMA), `.query` giống hệt văn bản gốc nên không
    # đổi hành vi chặn các biến thể quote/comment/qualify.
    try:
        called = _called_table_functions(con, statements[0].query, params)
    except duckdb.Error as e:
        raise SqlGuardError(f"Không phân tích được kế hoạch truy vấn: {e}") from e
    not_allowed = {f for f in called if f.lower() not in _ALLOWED_TABLE_FUNCTIONS}
    if not_allowed:
        raise SqlGuardError(
            f"Câu lệnh gọi hàm bảng không nằm trong allowlist: {sorted(not_allowed)}"
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
    assert_safe_sql(con, sql, params)
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
