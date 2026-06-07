"""Lưu trữ snapshot hằng ngày + chống lặp tin (best-effort).

Lưu ý thiết kế: tín hiệu danh mục và screener được tính từ lịch sử giá
LẤY MỚI mỗi lần chạy (vnstock trả về OHLCV lịch sử), nên hệ thống vẫn
chạy đúng kể cả khi DB chưa có dữ liệu cũ. DB ở đây chủ yếu để:
  - log lại bản tin mỗi ngày (tra cứu sau)
  - nhớ các tin đã gửi để không lặp lại
"""
import sqlite3
from pathlib import Path
from datetime import date

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "market.db"


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db():
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS portfolio_snapshot (
                run_date TEXT, symbol TEXT, close REAL, change_pct REAL,
                pnl_pct REAL, rsi REAL, ma20 REAL, ma50 REAL,
                vol_ratio REAL, pe REAL, pb REAL,
                PRIMARY KEY (run_date, symbol)
            );
            CREATE TABLE IF NOT EXISTS screener_result (
                run_date TEXT, symbol TEXT, score REAL, reason TEXT,
                PRIMARY KEY (run_date, symbol)
            );
            CREATE TABLE IF NOT EXISTS seen_news (
                news_id TEXT PRIMARY KEY, symbol TEXT, title TEXT, seen_date TEXT
            );
            CREATE TABLE IF NOT EXISTS digest_log (
                run_date TEXT PRIMARY KEY, content TEXT
            );
            """
        )


def save_portfolio(rows):
    with _conn() as c:
        c.executemany(
            """INSERT OR REPLACE INTO portfolio_snapshot
               VALUES (:run_date,:symbol,:close,:change_pct,:pnl_pct,
                       :rsi,:ma20,:ma50,:vol_ratio,:pe,:pb)""",
            rows,
        )


def save_screener(rows):
    with _conn() as c:
        c.executemany(
            "INSERT OR REPLACE INTO screener_result VALUES (:run_date,:symbol,:score,:reason)",
            rows,
        )


def filter_new_news(news_items):
    """Trả về danh sách tin CHƯA gửi và đánh dấu chúng là đã thấy."""
    fresh = []
    with _conn() as c:
        for n in news_items:
            nid = str(n.get("id") or n.get("title"))
            cur = c.execute("SELECT 1 FROM seen_news WHERE news_id=?", (nid,))
            if cur.fetchone() is None:
                fresh.append(n)
                c.execute(
                    "INSERT OR IGNORE INTO seen_news VALUES (?,?,?,?)",
                    (nid, n.get("symbol", ""), n.get("title", ""), date.today().isoformat()),
                )
    return fresh


def save_digest(content: str):
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO digest_log VALUES (?,?)",
            (date.today().isoformat(), content),
        )
