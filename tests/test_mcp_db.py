import threading

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


# Danh sách tích luỹ qua 5 vòng sửa của assert_safe_sql (lịch sử chi tiết ở
# task-1-report.md, mục "Vòng sửa 1-5"). Vòng 3 thay hẳn cơ chế
# statement-type: từ regex tự dò cú pháp SQL sang dùng chính parser DuckDB
# (duckdb.extract_statements) — chỉ SELECT duy nhất mới qua được. Vòng 3
# (đợt 2/3) thêm blocklist _DANGEROUS_TABLE_FUNCTIONS (checkpoint/
# force_checkpoint) và quy tắc tiền tố "__" — nhưng CẢ HAI vẫn dùng regex
# đoán TÊN HÀM từ chuỗi ký tự thô, bị vượt qua bằng "checkpoint"() (quote),
# checkpoint/**/() (comment chen giữa), main."checkpoint"() (qualify
# schema). Vòng 4 sửa bằng EXPLAIN (FORMAT JSON) — đọc tên hàm ĐÃ ĐƯỢC
# DUCKDB RESOLVE trong physical plan, miễn nhiễm cách viết — nhưng VẪN LÀ
# BLOCKLIST tên hàm. Vòng 5 phát hiện blocklist (dù đọc tên đúng) vẫn không
# đủ: catalog MotherDuck có 193 table-function, blocklist cũ chỉ chặn 12 —
# lọt 52 hàm họ MD_* không có tiền tố "__" (vd MD_DROP_DATABASE) và
# json_execute_serialized_sql (giấu một plan SQL khác, kể cả checkpoint(),
# làm tham số). Đảo hẳn thành ALLOWLIST (_ALLOWED_TABLE_FUNCTIONS trong
# mcp_server/db.py) — mặc định chặn mọi table-function không nằm trong
# danh sách cho phép. `assert_safe_sql` cần một connection (`con`) vì
# EXPLAIN cần bind vào catalog thật — đặc biệt quan trọng với hàm chỉ tồn
# tại trên MotherDuck.
#
# GIỚI HẠN CÒN LẠI (vòng 5, chưa giải quyết): cơ chế EXPLAIN chỉ bắt được
# TABLE-FUNCTION (hàm trong FROM). HÀM SCALAR nói chung — KHÔNG phân biệt có
# alias (`AS bất_kỳ_gì`) hay không — không sinh node "Function" trong plan
# nên không lọt vào diện được kiểm; alias chỉ khiến TÊN biểu thức gốc bị
# EXPLAIN ẩn thêm khỏi phần Projections/Expressions (không còn gì để đọc dù
# có muốn tự vá bằng text), chứ không phải điều kiện làm phát sinh lỗ hổng —
# ca không-alias cũng bị bỏ qua y hệt. Xem
# `test_scalar_function_is_not_blocked_known_gap` và task-1-report.md mục
# "Vòng sửa 5" để biết chi tiết + bằng chứng.
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
    "select * from checkpoint()",                                   # Vòng 3 (đợt 2): table-function side-effect thật
    "select * from force_checkpoint()",                             # cùng họ với checkpoint()
    "select * from \"checkpoint\"()",                                # Vòng 4: quote quanh tên hàm — vượt qua regex cũ, EXPLAIN vẫn resolve ra CHECKPOINT
    "select * from checkpoint/**/()",                               # Vòng 4: comment chen giữa tên hàm và dấu ngoặc
    "select * from \"force_checkpoint\"()",                          # Vòng 4: quote áp cho force_checkpoint — chính case mà regex _CALL_PATTERN cũ bỏ lọt vì tên dài bị ngắt dòng trong EXPLAIN text mặc định
    "PRAGMA enable_external_access=true",                           # đổi cấu hình thật — thử mở lại chính khoá đã đóng ở Task 1 gốc; type=SET, vẫn bị chặn
    "PRAGMA memory_limit='10GB'",                                   # đổi cấu hình thật; type=SET
    "PRAGMA force_checkpoint",                                      # side-effect thật qua cú pháp PRAGMA (không phải gọi hàm); type=PRAGMA
    "select * from __MD_FORCE_DETACH()",                            # Vòng 3 (đợt 3): hàm nội bộ MotherDuck — không tồn tại trên DuckDB local nên bị chặn qua nhánh "không phân tích được kế hoạch" (fail-closed), hành vi thật (dựa trên tên) đã xác nhận riêng trên md:vn_market, xem báo cáo
    "select * from __duck_panic()",                                 # cùng họ, tự thêm case
    "select * from __MD_RESET_BUFFER_MANAGER()",                    # cùng họ
    "select * from json_execute_serialized_sql(json_serialize_sql('select 41+1'))",  # Vòng 5, C1: nhận một plan SQL serialize làm tham số — có thể giấu checkpoint()/hàm nguy hiểm khác BÊN TRONG mà EXPLAIN câu ngoài không thấy (plan trong chưa deserialize); chặn được vì bản thân json_execute_serialized_sql không nằm trong allowlist — không cần biết nội dung serialize là gì
    "select * from md_is_connected()",                              # Vòng 5, C2: hàm MD_* KHÔNG dùng tiền tố "__" — blocklist vòng 4 bỏ lọt cả họ 52 hàm này; hàm này bản thân vô hại (đã xác nhận thực thi thật trả True) nhưng giờ vẫn bị chặn có chủ đích vì không nằm trong allowlist — KHÔNG PHẢI hồi quy
    "select * from md_pragma_version()",                            # cùng họ MD_* không tiền tố "__"
    "select * from enable_profiling()",                             # Vòng 5, I1: pragma-function đổi state connection dùng chung (_CON singleton) — guard vòng 4 cho qua vì không phải checkpoint/force_checkpoint và không có tiền tố "__"
]

MUST_ALLOW = [
    "SELECT * FROM t",
    "  select a, b from t where b = 'x'  ",
    "WITH c AS (SELECT * FROM t) SELECT count(*) FROM c",
    "select 'update me' as note from t",            # từ khoá nằm trong chuỗi, không phải lệnh
    "select replace(b, 'x', 'y') from t",           # "replace" là tên hàm đang gọi (dùng cột b — VARCHAR; EXPLAIN cần bind kiểu thật, replace(INTEGER,...) sẽ là Binder Error không liên quan tới rào chắn)
    "select a as update, b as delete, a as drop, b as insert from t",  # tên cột/bí danh trùng từ khoá cấm cũ (khái niệm FORBIDDEN đã bị xoá hoàn toàn ở vòng 3) — dùng alias vì EXPLAIN cần cột thật tồn tại để bind, khác với kiểm tra text thuần túy trước đây
    "select 1 -- it's a comment\nfrom t",           # dấu nháy đơn thật trong comment thật, không phải string literal
    "select 1 /* update */ from t",                 # từ khoá "cấm" cũ nằm trong block comment
    "select 1 -- update\nfrom t",                   # từ khoá "cấm" cũ nằm trong line comment
    "select (replace(b,'x','y')) as x from t",      # Vòng 3: allowlist vòng 2 chỉ trừ khỏi 1 trong 2 nhánh regex, bọc thêm ngoặc lại bị chặn nhầm
    "with x as (select replace(b,'x','y') from t) select * from x",
    "select $$hello$$ as x from t",                 # dollar-quote hợp lệ, không phải tấn công
    "PRAGMA database_list",                         # đọc thông tin thuần — DuckDB tự viết lại thành SELECT * FROM pragma_database_list(), không side-effect
    "PRAGMA show_tables",
    "PRAGMA version",
    "PRAGMA table_info('t')",
    "select a as checkpoint from t",                # Vòng 4: cột/bí danh trùng tên hàm nguy hiểm — không phải lời gọi hàm, EXPLAIN plan không sinh node "Function" cho việc này
]


@pytest.mark.parametrize("sql", MUST_BLOCK)
def test_assert_safe_sql_blocks_writes(con, sql):
    with pytest.raises(db.SqlGuardError):
        db.assert_safe_sql(con, sql)


@pytest.mark.parametrize("sql", MUST_ALLOW)
def test_assert_safe_sql_allows_reads(con, sql):
    db.assert_safe_sql(con, sql)


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


# I3 (fix round cuối): Global Constraint của plan A3 "giới hạn 1.000 dòng;
# timeout 30 giây" — giới hạn dòng có sẵn (min(limit, 1000)), timeout thì
# chưa. DuckDB không có statement_timeout built-in nên run_query() dùng
# threading.Timer(30, con.interrupt) quanh con.execute(). Không test thật
# 30 giây trôi qua (chậm, không cần thiết) — thay bằng FakeTimer để xác
# nhận ĐÚNG hành vi: Timer được tạo với (30, con.interrupt), start() trước
# execute, và cancel() được gọi trong finally ở CẢ hai nhánh (thành công
# lẫn lỗi).
class _FakeTimer:
    """Thay threading.Timer thật — ghi lại tham số/lời gọi thay vì chờ thật."""

    def __init__(self, interval, function):
        self.interval = interval
        self.function = function
        self.started = False
        self.cancelled = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True


def test_run_query_sets_30s_timer_and_cancels_after_success(con, monkeypatch):
    created = []

    def fake_timer_ctor(interval, function):
        t = _FakeTimer(interval, function)
        created.append(t)
        return t

    monkeypatch.setattr(threading, "Timer", fake_timer_ctor)
    rows = db.run_query(con, "SELECT a FROM t ORDER BY a")

    assert rows == [{"a": 1}, {"a": 2}, {"a": 3}]
    assert len(created) == 1
    assert created[0].interval == 30
    assert created[0].function == con.interrupt
    assert created[0].started is True
    assert created[0].cancelled is True   # phải cancel sau khi execute xong


def test_run_query_cancels_timer_even_when_execute_raises(con, monkeypatch):
    """Câu này qua được assert_safe_sql (PRAGMA đọc thông tin thuần, không
    side-effect) nhưng thất bại ở bước execute thật của run_query() — ca đã
    biết ("PRAGMA rút gọn không nhúng được vào subquery LIMIT", xem
    test_run_query_pragma_shorthand_fails_due_to_select_wrapping bên dưới).
    Tái dùng đúng ca lỗi có thật này để xác nhận timer.cancel() vẫn được
    gọi trong `finally` khi execute() ném lỗi — không cần giả lập lỗi giả
    bằng cách vá trực tiếp con.execute (DuckDBPyConnection không cho gán
    thuộc tính, đã tự xác minh)."""
    created = []

    def fake_timer_ctor(interval, function):
        t = _FakeTimer(interval, function)
        created.append(t)
        return t

    monkeypatch.setattr(threading, "Timer", fake_timer_ctor)
    with pytest.raises(duckdb.Error):
        db.run_query(con, "PRAGMA database_list")

    assert len(created) == 1
    assert created[0].cancelled is True


def test_assert_safe_sql_allows_paren_wrapped_function_call_and_executes_correctly(con):
    """Vòng 3, lỗ hổng #1: '(replace(...))' bọc thêm một ngoặc quanh lời gọi
    hàm từng bị chặn nhầm (allowlist ở vòng 2 chỉ trừ "replace" khỏi
    call_hit, quên trừ khỏi paren_hit). Với cơ chế EXPLAIN-based (vòng 4),
    hàm scalar không sinh node "Function" trong plan nên hoàn toàn miễn
    nhiễm với việc bọc ngoặc kiểu này — xác nhận cả assert_safe_sql cho qua
    lẫn kết quả thực thi đúng."""
    sql = "select (replace(b,'x','y')) as x from t"
    db.assert_safe_sql(con, sql)
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
        db.assert_safe_sql(con, sql)
    # Không bao giờ tới con.execute(sql) vì assert_safe_sql đã chặn ở trên.
    # Xác nhận bảng t vẫn còn tồn tại với đủ 3 dòng (không bị DROP).
    assert con.execute("SELECT count(*) FROM t").fetchone()[0] == 3


def test_escape_string_delete_survives_direct_execution_without_run_query(con):
    """Biến thể escape-string (E'...') của cùng lỗ hổng #2 — cùng lớp lỗi
    cú pháp trích dẫn DuckDB mà regex string-literal cũ (chỉ hiểu '...')
    không nhận diện được."""
    sql = "select E'\\'' as c from t; delete from t"
    with pytest.raises(db.SqlGuardError):
        db.assert_safe_sql(con, sql)
    assert con.execute("SELECT count(*) FROM t").fetchone()[0] == 3


def test_quoted_checkpoint_survives_direct_execution_without_run_query(con):
    """Vòng 4 — PoC re-reviewer dựng: trước khi sửa, '\"checkpoint\"()' (tên
    hàm đặt trong ngoặc kép) vượt qua cả hai regex đoán-tên-hàm của vòng 3
    (đợt 2/3) vì chuỗi ký tự chứa dấu nháy kép mà regex không tính tới. Xác
    nhận sau khi sửa: assert_safe_sql (dựa trên EXPLAIN, không đọc chuỗi
    gốc) chặn đúng, không phụ thuộc cách viết tên hàm."""
    sql = 'select * from "checkpoint"()'
    with pytest.raises(db.SqlGuardError):
        db.assert_safe_sql(con, sql)


def test_comment_split_checkpoint_survives_direct_execution_without_run_query(con):
    """Biến thể comment chen giữa tên hàm và dấu ngoặc — cùng lớp lỗi với
    quote, cùng được EXPLAIN-based check chặn đúng vì DuckDB đã resolve
    xong tên hàm trước khi ta đọc plan."""
    sql = "select * from checkpoint/**/()"
    with pytest.raises(db.SqlGuardError):
        db.assert_safe_sql(con, sql)


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
    "toàn lại không dùng được qua run_sql). Nằm ngoài phạm vi vá lần này — "
    "báo cáo cho coordinator quyết định thay vì tự sửa run_query() ngoài "
    "yêu cầu. Giữ nguyên không sửa theo đúng chỉ đạo vòng sửa 3 đợt 3."
))
def test_run_query_pragma_shorthand_fails_due_to_select_wrapping(con):
    db.assert_safe_sql(con, "PRAGMA database_list")  # xác nhận: guard cho qua đúng
    db.run_query(con, "PRAGMA database_list")        # nhưng thực thi qua run_query thì lỗi


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


def test_table_function_allowlist_does_not_false_positive_on_replace(con):
    """"replace" là hàm scalar (dùng trong SELECT list), không sinh node
    "Function" trong EXPLAIN plan (đó là node của table-function trong FROM)
    — nên không bao giờ bị so với `_ALLOWED_TABLE_FUNCTIONS`, không cần có
    mặt trong allowlist đó."""
    sql = "select replace(b,'x','y') as x from t"
    db.assert_safe_sql(con, sql)  # không ném lỗi
    rows = db.run_query(con, sql)
    assert rows == [{"x": "y"}, {"x": "y"}, {"x": "z"}]


@pytest.mark.xfail(strict=True, reason=(
    "Lỗ hổng CHƯA giải quyết (vòng sửa 5): hàm scalar KHÔNG bao giờ sinh "
    "node \"Function\" trong EXPLAIN plan (đó là node riêng của "
    "table-function trong FROM) nên không lọt vào diện được cơ chế này "
    "kiểm — có alias hay không đều như nhau, đã tự kiểm cả hai (`select "
    "write_log('hi')` và `select write_log('hi') as x` cùng ALLOW). Alias "
    "chỉ khiến vấn đề RÕ hơn: khi có alias, EXPLAIN (đã tự kiểm "
    "logical_plan/logical_opt/physical_plan qua explain_output='ALL', và "
    "duckdb_dependencies() sau PREPARE) còn ẩn luôn TÊN biểu thức gốc khỏi "
    "Projections/Expressions (chỉ còn tên alias) — nên dù có muốn tự vá "
    "bằng cách đọc text/JSON của EXPLAIN để suy ra tên hàm scalar, ca có "
    "alias cũng không còn gì để đọc. Không có cách chặn đáng tin cậy trong "
    "phạm vi cơ chế EXPLAIN/plan-text — báo cáo cho coordinator, không tự "
    "vá bằng regex trên text Projections (đã kiểm thêm: quy ước quote tên "
    "hàm trong Projections cũng không nhất quán — vd write_log('hi') không "
    "có ngoặc kép quanh tên hàm dù replace(...) thì có, và DuckDB tự "
    "hằng-số-hoá/constant-fold một số hàm scalar thuần trước khi tới "
    "EXPLAIN, nên ngay cả không có alias, việc trích tên hàm từ text cũng "
    "không đáng tin cậy)."
))
def test_scalar_function_is_not_blocked_known_gap(con):
    """Vòng 5 — giới hạn CHƯA giải quyết của cơ chế EXPLAIN-based: cơ chế chỉ
    kiểm TABLE-FUNCTION (node "Function" trong plan, sinh ra khi hàm được
    gọi trong mệnh đề FROM). Hàm SCALAR (gọi trong SELECT list, như
    `write_log(...)` — hàm DuckDB thật, side-effect ghi log) không sinh node
    này nên không bị lớp (3) kiểm, DÙ CÓ ALIAS (`AS bất_kỳ_tên_gì`) HAY
    KHÔNG — đã tự kiểm cả hai ca, cùng bị ALLOW như nhau (fix round cuối,
    M4: bản trước đóng khung sai giới hạn này là "chỉ khi có alias", tên
    test cũ `..._with_alias_...` gây hiểu nhầm y hệt — sửa lại câu chữ cho
    đúng thực tế, KHÔNG đổi phán quyết chấp nhận rủi ro). Khi có alias,
    EXPLAIN còn ẩn thêm TÊN biểu thức gốc khỏi output — đã tự kiểm ở cả 3
    giai đoạn plan (`explain_output='ALL'`: logical_plan, logical_opt,
    physical_plan) và qua `duckdb_dependencies()` sau `PREPARE` — không
    giai đoạn/API nào giữ lại tên hàm gốc một khi có alias, chỉ còn lại
    chuỗi alias.

    Test này CỐ TÌNH assert hành vi AN TOÀN mong muốn (chặn) rồi đánh dấu
    xfail — không phải vì đã có cách chặn, mà để ghi nhận công khai đây là
    lỗ hổng CHƯA có giải pháp trong phạm vi cơ chế EXPLAIN/plan-text, không
    lặng lẽ bỏ qua. `write_log` dùng làm hàm thay thế cho các hàm MotherDuck
    có side-effect thật cùng lớp (`MD_INTERRUPT_SERVER_CONNECTION`, `set_bit`)
    — đã tự xác nhận riêng trên md:vn_market qua `assert_safe_sql` (không
    thực thi) rằng `select md_interrupt_server_connection(<uuid>)` (cả có
    và không có alias) cũng KHÔNG bị chặn, cùng nguyên nhân."""
    sql = "select write_log('hi') as x"
    with pytest.raises(db.SqlGuardError):
        db.assert_safe_sql(con, sql)
