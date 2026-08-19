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

import pandas as pd
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
        SELECT id, symbol, event_title_vi, event_name_vi, distribution_type,
               exright_date, record_date, payout_date, public_date
        FROM stg_corporate_event
        WHERE symbol IN ({placeholders})
          AND id NOT IN (SELECT event_id FROM alert_sent_log)
        ORDER BY symbol, public_date
        """,
        symbols,
    ).df()
    return rows.to_dict(orient="records")


def split_symbols_by_seed_status(con, symbols: list[str]) -> tuple[list[str], list[str]]:
    """Chia `symbols` thành 2 nhóm dựa trên alert_sent_log — TỪNG mã riêng,
    không kiểm gộp cả danh sách:
      - symbols_can_bo_sung: mã CHƯA có dòng nào trong alert_sent_log
        (cần seed toàn bộ sự kiện hiện có, KHÔNG gửi Telegram cho riêng
        mã đó — coi như "lần đầu bật cảnh báo" của MÃ NÀY).
      - symbols_da_co: mã ĐÃ có ít nhất 1 dòng — xử lý bình thường (gửi
        tin nếu có sự kiện mới).

    Thay thế is_first_run(con, symbols) cũ (fix Important #2, review round
    1): is_first_run đếm TỔNG số dòng của CẢ danh sách symbols, nên khi
    config/portfolio.yml thêm 1 mã MỚI vào danh mục ĐANG chạy (các mã cũ
    đã có log), hàm cũ trả False cho toàn bộ danh sách — mã mới bị coi là
    "đã qua giai đoạn seed" và bị dội nguyên lịch sử sự kiện của nó vào 1
    tin Telegram ngay lập tức, đúng vấn đề mà cơ chế seed sinh ra để
    tránh. Chia theo TỪNG mã giải quyết đúng ca này: trạng thái seed của
    một mã không phụ thuộc trạng thái của các mã khác trong cùng danh mục.
    """
    if not symbols:
        return [], []
    placeholders = ", ".join(["?"] * len(symbols))
    seeded = {
        r[0]
        for r in con.execute(
            f"SELECT DISTINCT symbol FROM alert_sent_log WHERE symbol IN ({placeholders})",
            symbols,
        ).fetchall()
    }
    symbols_can_bo_sung = [s for s in symbols if s not in seeded]
    symbols_da_co = [s for s in symbols if s in seeded]
    return symbols_can_bo_sung, symbols_da_co


def _format_date(value) -> str:
    """Chuẩn hoá một giá trị ngày về chuỗi YYYY-MM-DD.

    fetch_unalerted_events lấy dữ liệu qua con.execute(...).df() — cột
    DATE của DuckDB đi qua pandas trở thành pandas.Timestamp (KHÔNG phải
    datetime.date thuần), nên str(value) trực tiếp in ra thừa phần giờ
    "00:00:00". pd.Timestamp(value) chấp nhận cả Timestamp lẫn date/
    datetime nên hàm này dùng chung được cho mọi nguồn gọi format_message.
    KHÔNG gọi hàm này cho giá trị NULL/NaT — kiểm bằng pd.isna() trước ở
    format_message (pd.Timestamp(NaT).strftime(...) vẫn ra chuỗi "NaT").
    """
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def format_message(events: list[dict], run_date: str) -> str:
    lines = [f"📅 Sự kiện DN mới ({run_date}):", ""]
    for e in events:
        # event_title_vi CÓ THỂ NULL (DDL raw_corporate_event không ràng
        # buộc NOT NULL cho cột này, stg_corporate_event.sql tự phòng thủ
        # bằng coalesce(event_title_vi, '') khi phân loại) — dùng e[...]
        # trực tiếp từng render literal "HPG — None" vào tin Telegram thật
        # (fix Important #1, final review). Dùng .get(...) + fallback qua
        # event_name_vi (cùng nguồn, luôn có nội dung), cuối cùng là
        # placeholder tiếng Việt rõ ràng — không bao giờ để lộ giá trị kỹ
        # thuật của Python vào tin nhắn thật.
        title = e.get("event_title_vi") or e.get("event_name_vi") or "(không có tiêu đề)"
        lines.append(f"{e['symbol']} — {title}")
        exright_date = e.get("exright_date")
        public_date = e.get("public_date")
        # pd.isna(...) — KHÔNG dùng `is not None`: cột DATE NULL của DuckDB
        # đi qua .df() trở thành pandas.NaT, và `NaT is not None` là True,
        # nên kiểm bằng is not None từng in thẳng literal "GDKHQ: NaT" vào
        # tin Telegram thật (fix Important #1, review round 1).
        if not pd.isna(exright_date):
            lines.append(f"  GDKHQ: {_format_date(exright_date)}")
        elif not pd.isna(public_date):
            lines.append(f"  Ngày công bố: {_format_date(public_date)}")
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

    # Chia theo TỪNG mã (fix Important #2, review round 1) — xem docstring
    # split_symbols_by_seed_status: mã mới thêm vào danh mục phải được seed
    # riêng, không phụ thuộc trạng thái của các mã khác đã chạy từ trước.
    symbols_can_bo_sung, symbols_da_co = split_symbols_by_seed_status(con, symbols)

    if symbols_can_bo_sung:
        seed_events = fetch_unalerted_events(con, symbols_can_bo_sung)
        event_ids = [e["id"] for e in seed_events]
        symbol_by_id = {e["id"]: e["symbol"] for e in seed_events}
        n = mark_events_alerted(con, event_ids, symbol_by_id)
        print(
            f"Mã mới trong danh mục ({', '.join(symbols_can_bo_sung)}) — "
            f"đã seed {n} sự kiện hiện có, KHÔNG gửi Telegram."
        )

    if not symbols_da_co:
        return  # toàn bộ danh mục vừa được seed lần đầu, không còn mã nào để gửi tin

    events = fetch_unalerted_events(con, symbols_da_co)
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
