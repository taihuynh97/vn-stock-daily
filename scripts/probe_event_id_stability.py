"""Kiểm chứng `id` của Company.events() có ổn định giữa các lần gọi không.

Toàn bộ cơ chế append-only của raw_corporate_event (B1) dựa vào giả định
này. Nếu nguồn sinh id mới mỗi lần gọi, dedup theo id sẽ vỡ và bảng phình
vô hạn sau mỗi lần chạy weekly.

Chạy:
    set -a && source .env && set +a
    .venv/bin/python -m scripts.probe_event_id_stability

Exit code 0 = id ổn định, dùng làm khoá dedup được.
Exit code 1 = id KHÔNG ổn định, phải đổi sang khoá thay thế.
"""
import os
import time

from dotenv import load_dotenv

load_dotenv()
if os.getenv("VNSTOCK_API_KEY"):
    from vnstock import vnai
    vnai.setup_api_key(os.getenv("VNSTOCK_API_KEY"))

from vnstock.api.company import Company

# Mẫu cố tình trộn mã năng động sự kiện (MWG, HPG) với mã ít sự kiện (VNR),
# vì cửa sổ 50 sự kiện của hai nhóm này phủ khoảng thời gian rất khác nhau
# (đo 2026-08-16: MWG 1,0 năm, VNR 9,4 năm) nên cơ chế sinh id có thể khác.
SYMBOLS = ["HPG", "VNM", "VCB", "MWG", "VNR"]
SLEEP_BETWEEN_CALLS = 1.05      # khớp VNSTOCK_MIN_INTERVAL của job thật
SLEEP_BETWEEN_ROUNDS = 60       # đủ dài để lộ id sinh theo timestamp/session


def snapshot(symbol: str) -> dict[str, tuple[str, str]]:
    """Trả {id: (event_code, exright_date)} cho một mã."""
    df = Company(symbol=symbol, source="VCI").events()
    df.columns = [str(c).lower() for c in df.columns]
    return {
        str(row["id"]): (str(row.get("event_code")), str(row.get("exright_date")))
        for _, row in df.iterrows()
    }


def main() -> int:
    print(f"Vòng 1: gọi events() cho {len(SYMBOLS)} mã...")
    first = {}
    for sym in SYMBOLS:
        first[sym] = snapshot(sym)
        time.sleep(SLEEP_BETWEEN_CALLS)

    print(f"Chờ {SLEEP_BETWEEN_ROUNDS} giây trước vòng 2...")
    time.sleep(SLEEP_BETWEEN_ROUNDS)

    print("Vòng 2: gọi lại và đối chiếu...")
    ok = True
    for sym in SYMBOLS:
        second = snapshot(sym)
        time.sleep(SLEEP_BETWEEN_CALLS)
        a, b = first[sym], second
        chung = set(a) & set(b)
        print(f"  {sym}: vòng 1 = {len(a)} id, vòng 2 = {len(b)} id, trùng = {len(chung)}")
        if not chung:
            print(f"    THẤT BẠI: không id nào trùng — id KHÔNG ổn định")
            ok = False
            continue
        lech = [k for k in chung if a[k] != b[k]]
        if lech:
            print(f"    THẤT BẠI: {len(lech)} id trùng nhưng nội dung khác — "
                  f"id bị tái sử dụng cho sự kiện khác")
            ok = False
        # Trùng < 90% nghĩa là id đổi phần lớn dù vẫn có một ít trùng —
        # vẫn coi là không ổn định, vì bảng sẽ phình gần như toàn bộ mỗi tuần.
        elif len(chung) < 0.9 * min(len(a), len(b)):
            print(f"    THẤT BẠI: chỉ {len(chung)}/{min(len(a), len(b))} id trùng "
                  f"(<90%) — id không đủ ổn định để dedup")
            ok = False

    print()
    if ok:
        print("KẾT LUẬN: id ỔN ĐỊNH — dùng làm khoá dedup append-only được. "
              "Tiếp tục Task 2.")
        return 0
    print("KẾT LUẬN: id KHÔNG ổn định — PHẢI đổi khoá dedup sang hash của "
          "(symbol, event_code, exright_date, event_title_vi) trước khi đi tiếp. "
          "BÁO CONTROLLER, KHÔNG tự đổi thiết kế.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
