# 06 — Tự động hoá (GitHub Actions & Scheduling)

## Files liên quan
- `.github/workflows/daily.yml` — gửi bản tin T2-T6
- `.github/workflows/warehouse.yml` — nạp giá EOD hằng ngày
- `.github/workflows/warehouse-weekly.yml` — nạp financials mỗi T7
- `.github/workflows/warehouse-monthly.yml` — nạp company info ngày 1 mỗi tháng

---

## GitHub Actions là gì?

GitHub Actions là CI/CD platform tích hợp trong GitHub. Với repo này, dùng để **chạy Python scripts theo lịch** — không cần server riêng.

**CI/CD** = Continuous Integration / Continuous Deployment.
- **CI**: Tự động test code khi push.
- **CD**: Tự động deploy khi merge. 
- Repo này dùng chủ yếu cho **scheduled jobs** (không phải CI/CD truyền thống).

---

## Cấu trúc một workflow file

```yaml
# .github/workflows/warehouse.yml
name: warehouse-daily           # tên hiển thị trong GitHub UI

on:
  schedule:
    - cron: "30 8 * * 1-5"     # trigger: cron schedule
  workflow_dispatch: {}         # trigger: chạy thủ công từ UI

jobs:
  warehouse-daily:              # tên job
    runs-on: ubuntu-latest      # máy chủ GitHub dùng

    steps:
      - uses: actions/checkout@v4              # clone repo
      - uses: actions/setup-python@v5          # cài Python
        with:
          python-version: "3.12"
          cache: pip                            # cache packages để nhanh hơn
      - run: pip install -r requirements.txt   # cài dependencies
      - name: Run warehouse job
        env:
          WAREHOUSE_DB: "md:vn_market"
          motherduck_token: ${{ secrets.MOTHERDUCK_TOKEN }}
          VNSTOCK_API_KEY: ${{ secrets.VNSTOCK_API_KEY }}
        run: python build_warehouse.py --mode daily
```

---

## Cron Syntax — Đọc lịch chạy

Cú pháp cron: `minute hour day-of-month month day-of-week`

```
"30 8 * * 1-5"
  │  │  │  │  └── Thứ 2-6 (1=Mon, 5=Fri)
  │  │  │  └───── Mọi tháng (*)
  │  │  └──────── Mọi ngày (*)
  │  └─────────── 8h UTC
  └────────────── phút 30
```

**Múi giờ**: GitHub Actions dùng UTC. Việt Nam là UTC+7.
- `8:30 UTC` = `15:30 ICT` — sau khi thị trường VN đóng cửa (15:00).

**Lịch các workflow:**

| Workflow | Cron | UTC | ICT | Nội dung |
|---|---|---|---|---|
| `warehouse.yml` | `30 8 * * 1-5` | T2-T6 8:30 | 15:30 | Giá EOD (chạy trước) |
| `daily.yml` | `0 9 * * 1-5` | T2-T6 9:00 | 16:00 | Bản tin (chạy sau) |
| `warehouse-weekly.yml` | `30 8 * * 6` | T7 8:30 | 15:30 | + Financials |
| `warehouse-monthly.yml` | `0 9 1 * *` | Ngày 1, 9:00 | 16:00 | + Company info |

---

## Job Ordering — Tại sao newsletter chạy sau warehouse?

Hai job `warehouse.yml` và `daily.yml` **không độc lập** về mặt dữ liệu:

```
warehouse.yml (08:30 UTC):
  vnstock API → MotherDuck (ghi giá EOD hôm nay)

daily.yml (09:00 UTC — 30 phút sau):
  MotherDuck → ingest.fetch_history → signals → newsletter
```

**Nếu chạy đồng thời (08:30):**
- Newsletter đọc MotherDuck ngay lúc warehouse đang ghi
- Có thể thiếu giá hôm nay → MA/RSI tính từ dữ liệu cũ một ngày

**Sau khi fix (daily.yml = 09:00 UTC):**
- Warehouse có 30 phút để hoàn thành (bulk API call, thường <15 phút)
- Newsletter đọc MotherDuck → có đủ lịch sử + giá hôm nay → threshold `max(days//2, 10)` đạt
- `fetch_history` trả từ warehouse, **không gọi API** → tiết kiệm ~96 giây (khoảng 31 lần gọi × 3.1s: VNINDEX + danh mục + ~27 mã screener)

**Lưu ý**: `fetch_ratios`, `fetch_industry`, `fetch_news` vẫn gọi API trực tiếp (chưa có warehouse-first). Chỉ `fetch_history` (OHLCV lịch sử) là phần tốn thời gian nhất và đã được tối ưu.

---

## Secrets Management — Bảo mật credentials

```yaml
env:
  motherduck_token: ${{ secrets.MOTHERDUCK_TOKEN }}
  VNSTOCK_API_KEY: ${{ secrets.VNSTOCK_API_KEY }}
```

**`${{ secrets.NAME }}`**: Đọc secret từ GitHub repository settings (Settings → Secrets and variables → Actions).

**Tại sao không hard-code trong file?**
- File workflow nằm trong repo → ai có quyền đọc repo cũng thấy.
- GitHub secrets được encrypt, chỉ exposed khi workflow chạy.
- Không bao giờ commit credentials vào git.

### File `.env` cho local development

```
MOTHERDUCK_TOKEN=eyJ...
VNSTOCK_API_KEY=vn123...
ANTHROPIC_API_KEY=sk-ant-...
TELEGRAM_BOT_TOKEN=1234:AAA...
TELEGRAM_CHAT_ID=123456
```

`python-dotenv` load file này khi chạy local:
```python
from dotenv import load_dotenv
load_dotenv()  # đọc .env → set os.environ
```

`.env` phải có trong `.gitignore` — **không bao giờ commit file này**.

---

## Multi-cadence Scheduling — Thiết kế lịch chạy nhiều tần suất

Phase 2A thiết kế 3 cadence (tần suất) khác nhau cho 3 loại dữ liệu:

| Dữ liệu | Tần suất | Lý do |
|---|---|---|
| Giá EOD | Hằng ngày | Thay đổi mỗi phiên |
| Tỷ số tài chính (P/E, ROE) | Hàng tuần | Cập nhật theo quý, không cần daily |
| Thông tin công ty | Hàng tháng | Hiếm khi thay đổi |

**Thiết kế này tối ưu API quota và compute.**

Cách thực thi: 1 script `build_warehouse.py`, 3 mode:

```bash
python build_warehouse.py --mode daily    # chỉ giá
python build_warehouse.py --mode weekly   # giá + financials
python build_warehouse.py --mode monthly  # giá + financials + company info
```

**Ưu điểm của 1 script + flag thay vì 3 script riêng:**
- DRY: logic khởi tạo (connect, init_warehouse) chỉ viết 1 lần.
- Dễ test: `python build_warehouse.py --help` cho biết đầy đủ options.
- Dễ chạy thủ công: không phải nhớ tên 3 file khác nhau.

---

## `workflow_dispatch` — Chạy thủ công

```yaml
on:
  schedule:
    - cron: "30 8 * * 6"
  workflow_dispatch: {}   # thêm dòng này
```

Với `workflow_dispatch`, bạn có thể vào GitHub UI → Actions → Chọn workflow → "Run workflow" để chạy ngay, không cần đợi cron.

**Hữu ích khi:**
- Test workflow sau khi thay đổi code.
- Chạy backfill thủ công.
- Recover sau khi workflow fail.

---

## So sánh các giải pháp scheduling

| Giải pháp | Ưu điểm | Nhược điểm | Phù hợp |
|---|---|---|---|
| **GitHub Actions** (đang dùng) | Free, zero infra, version control | Delay ±10 phút, không real-time | Daily batch jobs |
| **Cron trên server** | Chính xác, linh hoạt | Cần manage server, không fail-safe | Nếu đã có server |
| **Airflow** | DAG dependencies, UI, retry | Nặng, cần setup | Enterprise, nhiều jobs phức tạp |
| **Prefect** | Modern, Python native, cloud option | Subscription cho cloud | Medium complexity |
| **AWS EventBridge** | Managed, reliable | Có chi phí | Nếu đã dùng AWS |
| **Vercel Cron** | Serverless, rẻ | Chỉ cho HTTP endpoint | Nếu có web app |

---

## `cache: pip` — Tối ưu tốc độ workflow

```yaml
- uses: actions/setup-python@v5
  with:
    python-version: "3.12"
    cache: pip              # cache thư mục pip
```

Mỗi lần workflow chạy, GitHub khởi tạo máy mới (ubuntu-latest). Không có cache → phải `pip install` từ đầu mỗi lần (~30-60s).

Với `cache: pip`: GitHub lưu cached packages. Lần sau nếu `requirements.txt` không đổi → skip download (~5-10s).

**Trade-off nhỏ**: Cache có thể stale nếu package có security update mà không bump version trong `requirements.txt`. Nhưng với project internal, acceptable.

---

## Đọc hiểu workflow chạy như thế nào

```
GitHub cron trigger → spin up ubuntu VM
                    → checkout repo (git clone)
                    → setup Python 3.12
                    → pip install requirements
                    → inject secrets vào environment
                    → python build_warehouse.py --mode daily
                         │
                         ├─ connect MotherDuck (motherduck_token từ env)
                         ├─ gọi vnstock API (VNSTOCK_API_KEY từ env)
                         ├─ upsert data vào DuckDB cloud
                         └─ print log
                    → VM bị xóa (mọi file local mất, data trên MotherDuck vẫn còn)
```

**Quan trọng**: GitHub Actions VM là ephemeral (tạm thời). Sau mỗi lần chạy, VM bị destroy. Chỉ data lưu trên external storage (MotherDuck, SQLite... nhưng SQLite nằm trên VM nên cũng mất) mới persist.

**Vấn đề**: `storage.py` dùng SQLite file tại `data/market.db` — file này nằm trên VM → **mất sau mỗi lần chạy**. Đây là limitation của thiết kế hiện tại (Phase 3 sẽ migrate SQLite sang DuckDB/MotherDuck).
