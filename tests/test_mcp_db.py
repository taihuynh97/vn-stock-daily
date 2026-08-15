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


@pytest.mark.parametrize("sql", [
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
    "PRAGMA database_list",
    "SET threads = 1",
    "select 1; drop table t",          # nhiều câu lệnh
    "WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x",  # CTE ghi (DuckDB)
])
def test_assert_safe_sql_blocks_writes(sql):
    with pytest.raises(db.SqlGuardError):
        db.assert_safe_sql(sql)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM t",
    "  select a, b from t where b = 'x'  ",
    "WITH c AS (SELECT * FROM t) SELECT count(*) FROM c",
    "select 'update me' as note from t",    # từ khoá nằm trong chuỗi, không phải lệnh
    "select replace(a, 'x', 'y') from t",   # "replace" là tên hàm đang gọi
    "select update, delete, drop, insert from t",  # tên cột trùng từ khoá cấm
])
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


def test_get_readonly_conn_blocks_file_system_access(tmp_path, monkeypatch):
    """Vòng sửa 1: assert_safe_sql không (và không cần) bắt read_text/glob/
    read_csv — đây là hàm bảng đọc file, không phải lệnh ghi. Lớp chặn đúng
    là enable_external_access=false ở tầng kết nối DuckDB."""
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
