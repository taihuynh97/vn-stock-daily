import duckdb
import pytest

from mcp_server import db


@pytest.fixture
def con(tmp_path):
    path = tmp_path / "m.duckdb"
    c = duckdb.connect(str(path))
    c.execute("CREATE TABLE t (a INTEGER, b VARCHAR)")
    c.execute("INSERT INTO t VALUES (1,'x'), (2,'y'), (3,'z')")
    yield c
    c.close()


# Danh sách tích luỹ qua 3 vòng sửa của assert_safe_sql (lịch sử chi tiết ở
# task-1-report.md, mục "Vòng sửa 1/2/3"). Vòng 3 thay hẳn cơ chế: từ regex
# tự dò cú pháp SQL sang dùng chính parser DuckDB (duckdb.extract_statements)
# — chỉ SELECT duy nhất mới qua được, mọi loại câu lệnh khác bị từ chối mặc
# định (whitelist, không phải blacklist từ khoá). Vòng 3 (đợt sửa thứ hai)
# thêm một danh sách hẹp, hữu hạn `_DANGEROUS_TABLE_FUNCTIONS` (checkpoint/
# force_checkpoint) cho các table-function có side-effect quản trị mà cú
# pháp SELECT hợp lệ không tự phân biệt được — và xác nhận PRAGMA đọc thông
# tin thuần (database_list/show_tables/version/table_info) KHÔNG phải lỗ
# hổng: DuckDB tự phân loại chúng là SELECT vì chúng thật sự chỉ đọc
# metadata, còn mọi PRAGMA đổi cấu hình (memory_limit=, enable_external_
# access=, force_checkpoint) vẫn được phân loại SET/PRAGMA và vẫn bị chặn.
# Vòng 3 (đợt sửa thứ ba) thêm quy tắc TIỀN TỐ `_INTERNAL_FUNC_PATTERN`
# (`__` đứng đầu tên hàm) để chặn cả họ hàm nội bộ/quản trị của MotherDuck
# (__MD_*) và DuckDB (__DUCK_PANIC, __internal_*) — thay vì liệt kê từng
# tên, vì MotherDuck có thể thêm hàm __MD_* mới bất cứ lúc nào.
MUST_BLOCK = [
    "INSERT INTO t VALUES (9,'q')",
    "update t set a = 5",
    "DELETE FROM t",
    "drop table t",
    "CREATE TABLE u (a INT)",
    "ALTER TABLE t ADD COLUMN c INT",
    "ATTACH 'other.db'",
    "COPY t TO 'out.csv'",
    "INSTALL httpfs",
    "LOAD httpfs",
    "SET threads = 1",
    "select 1; drop table t",                                       # nhiều câu lệnh
    "WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x",         # không phải cú pháp DuckDB hợp lệ — parser tự báo lỗi ("A CTE needs a SELECT")
    "WITH a AS (SELECT 1), b AS (DELETE FROM t) SELECT * FROM a, b",  # tương tự, CTE thứ hai ghi
    "select '--' as c from t; delete from t",                       # Vòng 2: '--' trong chuỗi không được nuốt mất ';'
    "select $$x'$$ ; drop table t; -- $$y'$$ as z from t",          # Vòng 3: dollar-quote không được regex string-literal cũ nhận diện
    "select E'\\'' as c from t; delete from t",                     # Vòng 3: escape-string DuckDB, cùng lớp lỗi với dollar-quote
    "select * from checkpoint()",                                   # Vòng 3 (đợt 2): table-function side-effect thật, chặn bằng _DANGEROUS_TABLE_FUNCTIONS
    "select * from force_checkpoint()",                             # cùng họ với checkpoint(), tự thêm case (brief cũ không có)
    "PRAGMA enable_external_access=true",                           # đổi cấu hình thật — thử mở lại chính khoá đã đóng ở Task 1 gốc; type=SET, vẫn bị chặn
    "PRAGMA memory_limit='10GB'",                                   # đổi cấu hình thật; type=SET
    "PRAGMA force_checkpoint",                                      # side-effect thật qua cú pháp PRAGMA (không phải gọi hàm); type=PRAGMA
    "select * from __MD_FORCE_DETACH()",                            # Vòng 3 (đợt 3): hàm nội bộ MotherDuck, chặn bằng _INTERNAL_FUNC_PATTERN (tiền tố "__")
    "select * from __duck_panic()",                                 # cùng họ, tự thêm case (brief cũ không có)
    "select * from __MD_RESET_BUFFER_MANAGER()",                    # cùng họ, side-effect quản trị gợi ý qua tên
]

MUST_ALLOW = [
    "SELECT * FROM t",
    "  select a, b from t where b = 'x'  ",
    "WITH c AS (SELECT * FROM t) SELECT count(*) FROM c",
    "select 'update me' as note from t",            # từ khoá nằm trong chuỗi, không phải lệnh
    "select replace(a, 'x', 'y') from t",           # "replace" là tên hàm đang gọi
    "select update, delete, drop, insert from t",   # tên cột trùng từ khoá cấm cũ (khái niệm FORBIDDEN đã bị xoá hoàn toàn ở vòng 3)
    "select 1 -- it's a comment\nfrom t",           # dấu nháy đơn thật trong comment thật, không phải string literal
    "select 1 /* update */ from t",                 # từ khoá "cấm" cũ nằm trong block comment
    "select 1 -- update\nfrom t",                   # từ khoá "cấm" cũ nằm trong line comment
    "select (replace(a,'x','y')) as x from t",      # Vòng 3: phát hiện — allowlist vòng 2 chỉ trừ khỏi 1 trong 2 nhánh regex, bọc thêm ngoặc lại bị chặn nhầm
    "with x as (select replace(a,'x','y') from t) select * from x",
    "select $$hello$$ as x from t",                 # dollar-quote hợp lệ, không phải tấn công
    "PRAGMA database_list",                         # đọc thông tin thuần — DuckDB tự viết lại thành SELECT * FROM pragma_database_list(), không side-effect
    "PRAGMA show_tables",
    "PRAGMA version",
    "PRAGMA table_info('t')",
]


@pytest.mark.parametrize("sql", MUST_BLOCK)
def test_assert_safe_sql_blocks_writes(sql):
    with pytest.raises(db.SqlGuardError):
        db.assert_safe_sql(sql)


@pytest.mark.parametrize("sql", MUST_ALLOW)
def test_assert_safe_sql_allows_reads(sql):
    db.assert_safe_sql(sql)


def test_run_query_returns_dicts(con):
    rows = db.run_query(con, "SELECT a, b FROM t ORDER BY a")
    assert rows == [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}, {"a": 3, "b": "z"}]


def test_run_query_applies_limit(con):
    rows = db.run_query(con, "SELECT a FROM t ORDER BY a", limit=2)
    assert len(rows) == 2


def test_run_query_rejects_write(con):
    with pytest.raises(db.SqlGuardError):
        db.run_query(con, "DELETE FROM t")
    assert con.execute("SELECT count(*) FROM t").fetchone()[0] == 3


def test_assert_safe_sql_allows_paren_wrapped_function_call_and_executes_correctly(con):
    """Vòng 3, lỗ hổng #1: '(replace(...))' bọc thêm một ngoặc quanh lời gọi
    hàm từng bị chặn nhầm (allowlist ở vòng 2 chỉ trừ "replace" khỏi
    call_hit, quên trừ khỏi paren_hit). Với cơ chế mới (hỏi thẳng "toàn câu
    có phải SELECT không"), vị trí ngoặc không còn quan trọng — xác nhận cả
    assert_safe_sql cho qua lẫn kết quả thực thi đúng."""
    sql = "select (replace(b,'x','y')) as x from t"
    db.assert_safe_sql(sql)
    rows = db.run_query(con, sql)
    assert rows == [{"x": "y"}, {"x": "y"}, {"x": "z"}]


def test_dollar_quote_drop_survives_direct_execution_without_run_query(con):
    """Vòng 3, lỗ hổng #2 — PoC gốc do coordinator dựng: trước khi sửa,
    assert_safe_sql không nhận diện dollar-quote ($$...$$) nên câu này "qua"
    được; nếu code gọi con.execute() trực tiếp (không qua lớp bọc LIMIT của
    run_query) thì DROP TABLE thực thi thật — mất nguyên bảng, không chỉ mất
    dữ liệu. Xác nhận sau khi sửa: assert_safe_sql tự nó chặn được, không
    cần dựa vào lớp bọc của run_query để "được cứu" như trước."""
    sql = "select $$x'$$ ; drop table t; -- $$y'$$ as z from t"
    with pytest.raises(db.SqlGuardError):
        db.assert_safe_sql(sql)
    # Không bao giờ tới con.execute(sql) vì assert_safe_sql đã chặn ở trên.
    # Xác nhận bảng t vẫn còn tồn tại với đủ 3 dòng (không bị DROP).
    assert con.execute("SELECT count(*) FROM t").fetchone()[0] == 3


def test_escape_string_delete_survives_direct_execution_without_run_query(con):
    """Biến thể escape-string (E'...') của cùng lỗ hổng #2 — cùng lớp lỗi
    cú pháp trích dẫn DuckDB mà regex string-literal cũ (chỉ hiểu '...')
    không nhận diện được."""
    sql = "select E'\\'' as c from t; delete from t"
    with pytest.raises(db.SqlGuardError):
        db.assert_safe_sql(sql)
    assert con.execute("SELECT count(*) FROM t").fetchone()[0] == 3


@pytest.mark.xfail(strict=True, reason=(
    "Phát hiện khi tự kiểm chứng #6 của vòng sửa 3 (đợt 2) qua giao thức "
    "MCP thật: assert_safe_sql cho qua PRAGMA database_list/show_tables/"
    "version/table_info đúng (không phải lỗ hổng — DuckDB coi đây là SELECT "
    "thật). Nhưng run_query() bọc mọi câu bằng "
    "'SELECT * FROM (<sql>) LIMIT n', và cú pháp PRAGMA rút gọn (không có "
    "dấu = hay ngoặc thay thế) KHÔNG thể nhúng làm subquery trong ngoặc — "
    "DuckDB báo 'Parser Error: syntax error at or near \")\"'. Chạy trực "
    "tiếp (không bọc) thì đúng: con.execute('PRAGMA database_list') chạy "
    "được. Đây là lỗi CHỨC NĂNG của run_query, không phải lỗ hổng an ninh "
    "(không có gì bị mở quyền thêm — ngược lại, một câu đã được xác nhận an "
    "toàn lại không dùng được qua run_sql). Nằm ngoài phạm vi 'vá hẹp "
    "assert_safe_sql' được giao ở vòng này — báo cáo cho coordinator quyết "
    "định thay vì tự sửa run_query() ngoài yêu cầu."
))
def test_run_query_pragma_shorthand_fails_due_to_select_wrapping(con):
    db.assert_safe_sql("PRAGMA database_list")  # xác nhận: guard cho qua đúng
    db.run_query(con, "PRAGMA database_list")   # nhưng thực thi qua run_query thì lỗi


def test_get_readonly_conn_blocks_file_system_access(tmp_path, monkeypatch):
    """Vòng 1: assert_safe_sql không (và không cần) bắt read_text/glob/
    read_csv — đây là hàm bảng đọc file, không phải lệnh ghi. Lớp chặn đúng
    là enable_external_access=false ở tầng kết nối DuckDB, độc lập với
    assert_safe_sql."""
    monkeypatch.setenv("WAREHOUSE_DB", str(tmp_path / "w.duckdb"))
    con, _ = db.get_readonly_conn()
    try:
        with pytest.raises(Exception):
            con.execute("select * from read_text('.env')").fetchall()
        with pytest.raises(Exception):
            con.execute("select * from glob('**')").fetchall()
        # truy vấn bình thường vẫn chạy được sau khi khoá external access.
        assert con.execute("select 1").fetchone() == (1,)
    finally:
        con.close()


def test_dangerous_table_function_check_does_not_false_positive_on_replace(con):
    """_DANGEROUS_TABLE_FUNCTIONS chỉ chứa {"checkpoint", "force_checkpoint"}
    — xác nhận không hồi quy với "replace" (tên hàm không nằm trong danh
    sách này, đây là danh sách đóng dựa trên duckdb_functions(), không phải
    quét từ khoá chung chung)."""
    sql = "select replace(b,'x','y') as x from t"
    db.assert_safe_sql(sql)  # không ném lỗi
    rows = db.run_query(con, sql)
    assert rows == [{"x": "y"}, {"x": "y"}, {"x": "z"}]
