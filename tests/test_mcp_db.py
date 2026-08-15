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
# định (whitelist, không phải blacklist từ khoá).
#
# CHÚ Ý: "PRAGMA database_list" (1 trong 13 câu gốc) và
# "select * from checkpoint()" (thêm ở vòng 2) KHÔNG có trong MUST_BLOCK bên
# dưới — xem 2 test xfail(strict=True) cuối file, đây là lỗ hổng CHƯA giải
# quyết được phát hiện ở vòng 3, đã báo cáo cho coordinator, không tự ý loại
# khỏi yêu cầu hay tự vá bằng regex.
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


# --- Lỗ hổng ĐÃ BIẾT, CHƯA giải quyết (phát hiện ở vòng sửa 3) ---
#
# Cả hai test dưới đây dùng xfail(strict=True) thay vì bị âm thầm loại khỏi
# MUST_BLOCK hoặc "nới" thành pass giả: nếu ai đó sau này vô tình sửa
# assert_safe_sql theo hướng chặn được 2 case này, strict=True sẽ làm test
# suite BÁO LỖI (XPASS) để bắt buộc rà lại và gỡ marker — không để một fix
# âm thầm trôi qua mà không ai để ý, và không để lỗ hổng âm thầm trôi qua
# mà không ai để ý.

@pytest.mark.xfail(strict=True, reason=(
    "checkpoint() là table function DuckDB thật (flush WAL ra đĩa — "
    "side-effect thật). Nhưng cú pháp 'SELECT * FROM checkpoint()' được "
    "duckdb.extract_statements phân loại statement.type=SELECT, giống hệt "
    "'SELECT * FROM read_csv(...)' — whitelist theo statement.type không "
    "phân biệt được. read_only=True và enable_external_access=false đều "
    "không chặn (đã tự kiểm thực nghiệm: checkpoint() chạy thành công trên "
    "cả hai). Không có quy tắc regex nào vá được việc này đáng tin cậy hơn "
    "— đó chính là lý do rời bỏ regex ở vòng 3. Đã báo cáo cho coordinator, "
    "không tự chế thêm quy tắc để vá."
))
def test_assert_safe_sql_blocks_checkpoint_function_call():
    with pytest.raises(db.SqlGuardError):
        db.assert_safe_sql("select * from checkpoint()")


@pytest.mark.xfail(strict=True, reason=(
    "PRAGMA database_list là 1 trong 13 câu gốc yêu cầu 'phải vẫn chặn'. "
    "Nhưng DuckDB tự viết lại các PRAGMA đọc thuần dạng gọi-hàm (database_"
    "list, show_tables, version, table_info) thành 'SELECT * FROM pragma_"
    "xxx()' ngay ở tầng parser — statement.type trả về là SELECT. Khác với "
    "PRAGMA có side-effect thật (vd 'PRAGMA memory_limit=...', 'PRAGMA "
    "force_checkpoint') vẫn được phân loại đúng là SET/PRAGMA và vẫn bị "
    "chặn — đã tự kiểm thực nghiệm cả hai nhóm. Không tự ý loại câu này "
    "khỏi MUST_BLOCK dù tin rằng nó vô hại (đọc thuần, không side-effect) "
    "— đây là quyết định của coordinator, không phải của người triển khai."
))
def test_assert_safe_sql_blocks_pragma_database_list():
    with pytest.raises(db.SqlGuardError):
        db.assert_safe_sql("PRAGMA database_list")
