"""Điều phối job: ingest -> signals -> screener -> AI digest -> Telegram.

Chạy: python main.py
Yêu cầu biến môi trường: ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
(tuỳ chọn: CLAUDE_MODEL, VNSTOCK_API_KEY)
"""
import os
from datetime import date
from pathlib import Path
import yaml
from dotenv import load_dotenv

from src import ingest, signals, screener, digest, notify, storage

load_dotenv()
ROOT = Path(__file__).resolve().parent


def load_yaml(name):
    with open(ROOT / "config" / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    vnstock_key = os.getenv("VNSTOCK_API_KEY")
    if vnstock_key:
        from vnstock import vnai
        vnai.setup_api_key(vnstock_key)

    run_date = date.today().isoformat()
    storage.init_db()

    pf = load_yaml("portfolio.yml")
    scfg = load_yaml("screener.yml")
    source = pf.get("source", "VCI")

    # 0) Bối cảnh thị trường
    market = ingest.fetch_index("VNINDEX", source)

    # 1) Danh mục (kèm nhãn ngành)
    portfolio_rows, all_news = [], []
    for h in pf["holdings"]:
        sym = h["symbol"]
        df = ingest.fetch_history(sym, source, days=120)
        sig = signals.analyze(df)
        ratios = ingest.fetch_ratios(sym, source)
        row = signals.portfolio_row(sym, h, sig, ratios, run_date)
        row["industry"] = ingest.fetch_industry(sym, source)
        portfolio_rows.append(row)
        all_news += ingest.fetch_news(sym, source, limit=3)
    storage.save_portfolio(portfolio_rows)

    # 2) Screener (loại trừ mã đã giữ)
    held = {h["symbol"] for h in pf["holdings"]}
    screener_rows = screener.run(scfg, source, run_date, exclude=held)
    storage.save_screener(screener_rows)
    for r in screener_rows[:3]:
        all_news += ingest.fetch_news(r["symbol"], source, limit=2)

    # 3) Chỉ giữ tin chưa gửi
    fresh_news = storage.filter_new_news(all_news)

    # 4) AI tổng hợp (kèm bối cảnh thị trường)
    content = digest.build(run_date, market, portfolio_rows, screener_rows, fresh_news)
    storage.save_digest(content)

    # 5) Gửi Telegram
    notify.send(content)
    print("Đã gửi bản tin.")


if __name__ == "__main__":
    main()
