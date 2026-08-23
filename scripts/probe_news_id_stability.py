"""Kiểm chứng id tin tức (Company.news()) có ổn định giữa các lần gọi hay
không, trước khi dùng làm khoá append-only cho raw_news.

Company.news() trả ĐÚNG 50 dòng cho HPG (đã đo 2026-08-23) — trùng khớp
cửa sổ 50-sự-kiện đã biết của Company.events() (B1), cùng họ API
`Company`. Nếu id không ổn định hoặc cửa sổ không trượt như dự đoán, thiết
kế append-only ở Task 2 sẽ sai.

Chạy:
    set -a && source .env && set +a
    .venv/bin/python -m scripts.probe_news_id_stability

Exit code 0 = id ổn định, dùng append-only được.
Exit code 1 = KHÔNG ổn định, phải đổi khoá trước khi đi tiếp.
"""
import os
import time

from dotenv import load_dotenv

load_dotenv()
if os.getenv("VNSTOCK_API_KEY"):
    from vnstock import vnai
    vnai.setup_api_key(os.getenv("VNSTOCK_API_KEY"))

from vnstock.api.company import Company

# 5 mã portfolio thật (config/portfolio.yml) — đúng phạm vi raw_news sẽ dùng.
SAMPLES = ["HPG", "IDV", "MLS", "PHP", "VNR"]
SLEEP_BETWEEN_CALLS = 1.05
SLEEP_BETWEEN_ROUNDS = 60


def snapshot(symbol: str) -> dict[str, str]:
    """Trả {id: news_title} cho tin tức hiện có của 1 mã."""
    df = Company(symbol=symbol, source="VCI").news()
    if df is None or len(df) == 0:
        return {}
    df.columns = [str(c).lower() for c in df.columns]
    return dict(zip(df["id"].astype(str), df["news_title"].astype(str)))


def main() -> int:
    print(f"Vòng 1: gọi {len(SAMPLES)} mã...")
    first = {}
    for sym in SAMPLES:
        first[sym] = snapshot(sym)
        time.sleep(SLEEP_BETWEEN_CALLS)

    print(f"Chờ {SLEEP_BETWEEN_ROUNDS} giây trước vòng 2...")
    time.sleep(SLEEP_BETWEEN_ROUNDS)

    print("Vòng 2: gọi lại và đối chiếu...")
    ok = True
    for sym in SAMPLES:
        second = snapshot(sym)
        time.sleep(SLEEP_BETWEEN_CALLS)
        a, b = first[sym], second
        # Tin CÙNG id ở cả 2 vòng phải giữ NGUYÊN tiêu đề — id không được
        # tái sử dụng cho nội dung khác.
        common_ids = set(a) & set(b)
        changed = [i for i in common_ids if a[i] != b[i]]
        if changed:
            print(f"  {sym}: THẤT BẠI — {len(changed)} id giữ nguyên nhưng "
                  f"đổi tiêu đề. Ví dụ id={changed[0]!r}: "
                  f"vòng 1={a[changed[0]]!r} vòng 2={b[changed[0]]!r}")
            ok = False
        else:
            print(f"  {sym}: {len(common_ids)} id chung giữ nguyên tiêu đề, "
                  f"{len(set(b) - set(a))} id mới xuất hiện ở vòng 2, "
                  f"{len(set(a) - set(b))} id rơi khỏi cửa sổ — OK")

    print()
    if ok:
        print("KẾT LUẬN: id tin tức ỔN ĐỊNH — dùng append-only được. "
              "Tiếp tục Task 2.")
        return 0
    print("KẾT LUẬN: id tin tức KHÔNG ổn định — PHẢI xem lại thiết kế "
          "trước khi đi tiếp. BÁO CONTROLLER, KHÔNG tự đổi thiết kế.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
