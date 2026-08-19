"""Cảnh báo sự kiện DN cho danh mục — thay dần bản tin hằng ngày (C2).

Chạy: python alert_events.py
Yêu cầu biến môi trường: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
WAREHOUSE_DB (đặt 'md:vn_market' để đọc MotherDuck), motherduck_token
(nếu dùng MotherDuck).

KHÔNG đụng main.py/digest.py/daily.yml — chạy song song, độc lập hoàn
toàn. Không dùng SQLite cục bộ (src/storage.py) để chống lặp tin — dùng
bảng alert_sent_log trên warehouse (bền hơn cơ chế cache-based của
storage.py, tự nhận là "best-effort" trong docstring của chính nó).
"""
from datetime import date
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src import notify
from src.warehouse import get_conn, init_warehouse, mark_events_alerted

load_dotenv()
ROOT = Path(__file__).resolve().parent
DEFAULT_PORTFOLIO_PATH = ROOT / "config" / "portfolio.yml"


def load_portfolio_symbols(path=None) -> list[str]:
    p = Path(path) if path else DEFAULT_PORTFOLIO_PATH
    with open(p, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return [h["symbol"] for h in cfg["holdings"]]


def fetch_unalerted_events(con, symbols: list[str]) -> list[dict]:
    """Sự kiện DN của `symbols` CHƯA có trong alert_sent_log."""
    if not symbols:
        return []
    placeholders = ", ".join(["?"] * len(symbols))
    rows = con.execute(
        f"""
        SELECT id, symbol, event_title_vi, distribution_type,
               exright_date, record_date, payout_date, public_date
        FROM stg_corporate_event
        WHERE symbol IN ({placeholders})
          AND id NOT IN (SELECT event_id FROM alert_sent_log)
        ORDER BY symbol, public_date
        """,
        symbols,
    ).df()
    return rows.to_dict(orient="records")


def is_first_run(con, symbols: list[str]) -> bool:
    """True nếu alert_sent_log CHƯA có dòng nào cho các mã trong `symbols`."""
    if not symbols:
        return False
    placeholders = ", ".join(["?"] * len(symbols))
    n = con.execute(
        f"SELECT count(*) FROM alert_sent_log WHERE symbol IN ({placeholders})",
        symbols,
    ).fetchone()[0]
    return n == 0


def format_message(events: list[dict], run_date: str) -> str:
    lines = [f"📅 Sự kiện DN mới ({run_date}):", ""]
    for e in events:
        lines.append(f"{e['symbol']} — {e['event_title_vi']}")
        if e.get("exright_date") is not None:
            lines.append(f"  GDKHQ: {e['exright_date']}")
        elif e.get("public_date") is not None:
            lines.append(f"  Ngày công bố: {e['public_date']}")
        lines.append("")
    return "\n".join(lines).rstrip()


def main(portfolio_path=None):
    # LƯU Ý (lệch so với brief gốc): KHÔNG con.close() ở cuối hàm.
    # get_conn() trong test được monkeypatch để trả về connection CHIA SẺ
    # với fixture `con` của test (test cần đọc lại alert_sent_log sau khi
    # main() chạy xong) — đóng connection ở đây sẽ đóng luôn connection đó,
    # khiến assertion sau lệnh gọi main() trong test chết với
    # duckdb.ConnectionException: Connection already closed. Script này
    # chạy một lần rồi thoát tiến trình (không phải service dài hạn), và
    # DuckDB auto-commit mỗi câu lệnh nên không cần close() để đảm bảo dữ
    # liệu được ghi — an toàn khi bỏ qua bước đóng tường minh.
    con = get_conn()
    init_warehouse(con)
    symbols = load_portfolio_symbols(portfolio_path)
    run_date = date.today().isoformat()

    if is_first_run(con, symbols):
        events = fetch_unalerted_events(con, symbols)
        event_ids = [e["id"] for e in events]
        symbol_by_id = {e["id"]: e["symbol"] for e in events}
        n = mark_events_alerted(con, event_ids, symbol_by_id)
        print(f"Lần đầu chạy alert_events — đã seed {n} sự kiện hiện có, KHÔNG gửi Telegram.")
        return

    events = fetch_unalerted_events(con, symbols)
    if not events:
        print("Không có sự kiện DN mới.")
        return

    text = format_message(events, run_date)
    notify.send(text)
    event_ids = [e["id"] for e in events]
    symbol_by_id = {e["id"]: e["symbol"] for e in events}
    mark_events_alerted(con, event_ids, symbol_by_id)
    print(f"Đã gửi cảnh báo {len(events)} sự kiện mới, đã ghi log.")


if __name__ == "__main__":
    main()
