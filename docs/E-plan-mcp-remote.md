# Mảng E — Đưa MCP server lên remote để dùng từ claude.ai + điện thoại

**Mục tiêu:** hỏi phân tích cơ bản từ điện thoại/máy tính qua claude.ai (gói Pro),
không cần bật Claude Code trên máy Mac.

**Ngày lập:** 2026-08-25 · **Bản:** v4 · **Trạng thái:** chưa bắt đầu

---

## Đổi gì so với v1

v1 viết bằng suy luận ở vài chỗ; v2 viết sau khi kiểm chứng thật trên chính repo
này và đối chiếu tài liệu MCP spec / Anthropic / MotherDuck.

| # | Thay đổi | Lý do |
|---|---|---|
| 1 | **Thêm E0 — Read Scaling token**, làm trước tiên | v1 coi lỗ hổng hàm scalar là "rủi ro chấp nhận có điều kiện". Thực ra đóng được hẳn, chi phí gần bằng 0 |
| 2 | **Thêm `stateless_http=True`** vào E1 | v1 chỉ nói đổi `mcp.run(transport=...)`. Không đủ — sẽ lỗi "session not found" trên serverless |
| 3 | **Thêm cấu hình `transport_security`** vào E1 | DNS rebinding protection bật mặc định với allowlist rỗng → chặn luôn request từ Anthropic cloud |
| 4 | **Đảo thứ tự E2/E3** — deploy ingress hạn chế trước, mở public sau khi có auth | v1 tạo cửa sổ thời gian server public chưa auth |
| 5 | **Rút lại đường lui "bí mật trong URL"** | Tài liệu Anthropic nói rõ không khuyến nghị. Thay bằng `static_headers` beta |
| 6 | **Thêm PRM endpoint vào E3**, ước lượng lại 2–4h → 1–2 ngày | MCP spec yêu cầu MUST implement RFC9728; v1 bỏ sót |
| 7 | Thêm **baseline** và **cách tắt khẩn cấp** | v1 không có |

### v3 (25/08/2026) — sau khi phát hiện MotherDuck sắp chạm trần 10GB

| # | Thay đổi | Lý do |
|---|---|---|
| 8 | **E0 viết lại theo thuộc tính, không theo cơ chế** | v2 ghi "tạo Read Scaling token" — cơ chế riêng của MotherDuck. Migrate là mất thuộc tính bảo mật mà không ai nhận ra |
| 9 | **Thêm §2b — tính di động khi đổi warehouse** | Trả lời trực tiếp: đổi cloud không ảnh hưởng phần MCP public |
| 10 | **Thêm ràng buộc: giữ phương ngữ DuckDB** | Quyết định kiến trúc có chủ đích, không phải tình cờ. Đây là thứ quyết định chi phí migrate |
| 11 | **Tách `/health` và `/ready`** | Sự cố MotherDuck ngày 25/08 cho thấy `/health` trả 200 trong khi mọi tool đều lỗi |
| 12 | **Thêm §2c — trần lưu trữ** | 8,6/10GB. Rủi ro cao hơn mọi thứ trong mảng E: chạm trần thì ingestion hỏng, public hay không cũng vậy |

### v4 (25/08/2026) — sau câu hỏi "R2 cũng 10GB thì khác gì?"

| # | Thay đổi | Lý do |
|---|---|---|
| 13 | **Phát hiện ràng buộc thật: MotherDuck free = 10 giờ compute/tháng** | v3 chỉ nhìn storage. Compute nhiều khả năng mới là thứ đang siết, và là lý do duy nhất khiến việc rời MotherDuck có ý nghĩa |
| 14 | **Hạ bậc R2/S3 trong bảng §2b** | R2 cũng trần 10GB → không gỡ được ràng buộc; và đọc file qua httpfs **buộc tắt `enable_external_access=false`**, mất một lớp bảo mật |
| 15 | **Nâng Oracle Always Free lên lựa chọn hàng đầu** | 200GB storage + compute không giới hạn + file local nên giữ được cả 3 lớp bảo mật |
| 16 | Sửa tiêu chí so sánh của §2b | v3 so phương ngữ SQL (đúng nhưng phụ) mà bỏ qua quota compute (thứ siết thật) |

---

## 0. Bối cảnh & những gì đã sẵn sàng

| Thành phần | Trạng thái |
|---|---|
| Warehouse `md:vn_market` trên MotherDuck | ✅ Đã cloud, không phải di chuyển |
| 6 GitHub Actions workflow (daily/weekly/monthly + dbt build) | ✅ Chạy độc lập, máy cá nhân không tham gia |
| 13 MCP tool + `instructions.md` | ✅ Đã viết xong, không phải sửa logic |
| Skill `graham-fundamental-analysis` | ✅ Đã đúng format claude.ai cần (folder + `SKILL.md`) |
| Rào chắn SQL 3 lớp trong `db.py` | ✅ Đã có (xem 1.2 về giới hạn) |
| **Transport HTTP** | ❌ Đang là stdio |
| **Hosting công khai + HTTPS** | ❌ Chưa có |
| **Xác thực** | ❌ Chưa có |

### Đã kiểm chứng trên chính repo này (25/08/2026)

| Kiểm tra | Kết quả |
|---|---|
| Phiên bản SDK | `mcp 1.29.0` — có sẵn `stateless_http`, `json_response`, `token_verifier`, `auth`, `transport_security` |
| `duckdb.connect("md:vn_market", read_only=True)` | ✅ **MotherDuck CHẤP NHẬN** → `is_readonly=True`. Docstring `db.py` lo ngại "có thể không nhận" — thực tế nhận |
| `TransportSecuritySettings` mặc định | `enable_dns_rebinding_protection=True`, `allowed_hosts=[]`, `allowed_origins=[]` |
| `FastMCP.run()` signature | Chỉ nhận `transport` + `mount_path` → **`stateless_http` phải đặt ở constructor `FastMCP(...)`** |

### Điều kiện phía Anthropic

- Custom connector qua remote MCP: có trên **Free, Pro, Max, Team, Enterprise**
- Mobile iOS/Android dùng được; **cấu hình một lần trên claude.ai web**, tự sync
- Custom Skills upload ZIP: có trên Pro (cần bật code execution)
- Claude gọi server **từ cloud của Anthropic**, không phải từ máy bạn → server buộc phải public

---

## 1. Ba phát hiện kỹ thuật — phải xử lý, không phải tuỳ chọn

### 1.1 Lỗi tương tranh sẽ phát tác đúng lúc đổi sang HTTP

`server.py` giữ **một connection singleton** (`_CON`) dùng chung mọi request.
`db.run_query()` khởi động `threading.Timer(30, con.interrupt)` trước mỗi truy vấn.

Với **stdio**, request xử lý tuần tự → tối đa 1 truy vấn tại một thời điểm, vấn đề
không lộ ra. Docstring `db.py` đã lường trước:

> *"nếu không cancel, timer vẫn sống và có thể `interrupt()` nhầm một câu truy vấn
> KHÁC chạy sau đó trên cùng connection"*

Với **streamable-http**, uvicorn xử lý request đồng thời:
1. Hai truy vấn chạy song song trên **cùng một** DuckDB connection — không an toàn.
2. Timer của request A gọi `con.interrupt()` **giết truy vấn của request B**.
   Biểu hiện: lỗi ngẫu nhiên, không tái hiện, chỉ xảy ra khi hỏi nhiều mã liên tiếp.

**Xử lý — hai tầng, làm cả hai:**
- **Tầng hạ tầng (ưu tiên):** Cloud Run `--concurrency=1` → mỗi container xử lý một
  request tại một thời điểm. Lỗi biến mất **mà không đụng `db.py`**.
- **Tầng code (bảo hiểm):** `threading.Lock` quanh `run_query`. Cần vì HF Spaces
  không có nút `--concurrency`, và vì không nên phụ thuộc hoàn toàn vào cấu hình
  hạ tầng cho một bất biến về tính đúng đắn.

> Đây là nguyên tắc chung của mảng E: **dùng cấu hình hạ tầng trước, sửa code sau.**

### 1.2 Lỗ hổng hàm scalar — đóng được hẳn, đừng chấp nhận

`db.py` ghi rõ: lớp allowlist chỉ kiểm **table-function** (hàm trong mệnh đề `FROM`).
**Hàm scalar** có side-effect trên MotherDuck (`MD_INTERRUPT_SERVER_CONNECTION`,
`write_log`, `set_bit`) **không bị chặn**.

Tin tốt đã kiểm chứng: `read_only=True` **được MotherDuck chấp nhận**, nên lớp 1 đang
hoạt động — tình hình tốt hơn docstring lo ngại. Nhưng cờ read-only phía **client**
không đảm bảo chặn được hàm **admin phía server**.

**Lời giải đúng tầng: MotherDuck Read Scaling token** (xem E0). Token này chỉ cho
phép `SELECT`, chặn write và administrative operations — cưỡng chế ở phía MotherDuck,
không phụ thuộc rào chắn ứng dụng hay cờ client.

v1 coi đây là "rủi ro chấp nhận có điều kiện, auth là lớp phòng thủ chính". **v2 đảo
lại:** đóng lỗ hổng ở E0, auth quay về đúng vai trò lớp bổ sung. Hệ quả quan trọng:
nếu E3 kéo dài, rủi ro thấp hơn nhiều so với v1.

### 1.3 Hai cạm bẫy cấu hình chỉ lộ ra sau khi deploy

**(a) Session trên serverless.** streamable-http mặc định giữ session phía server.
Cloud Run scale-to-zero + nhiều instance → request thứ hai rơi vào container khác →
**"session not found"**. Container cũng bị tắt khi nhàn rỗi, session bốc hơi giữa chừng.
Đúng kịch bản dùng từ điện thoại: hỏi một câu, đọc 2 phút, hỏi tiếp.
→ Bắt buộc `stateless_http=True` **ở constructor**, không phải ở `run()`.

**(b) DNS rebinding protection.** Bật mặc định, allowlist rỗng. Deploy sau load
balancer, `Host` header là domain công khai → **server từ chối mọi request từ
Anthropic cloud**. Biểu hiện đánh lừa: `/health` trả 200 (không qua lớp này) nhưng
connector báo lỗi kết nối — rất dễ đổ oan cho OAuth.
→ Phải cấu hình `transport_security` với `allowed_hosts`/`allowed_origins` thật.

---

## 2. Hosting miễn phí — so sánh

Cloudflare Workers loại từ đầu: DuckDB Python không chạy trên runtime của Workers.

| Nền tảng | Thực sự free? | Cold start | Thẻ | Ghi chú |
|---|---|---|---|---|
| **Google Cloud Run** | ✅ 2M req/tháng, scale-to-zero | 5–15s lần đầu, sau đó ấm ~15 phút | Cần | Có `--ingress` và `--concurrency` — hai nút cần cho E2/1.1 |
| **Hugging Face Spaces (Docker)** | ✅ Hoàn toàn | Ngủ sau ~48h | **Không** | Ít ma sát nhất, có Secrets, Space đặt private được. Không có nút concurrency |
| Render (free web service) | ✅ 750h/tháng | 30–60s | Không | Cold start đau khi hỏi từ điện thoại |
| Oracle Cloud Always Free | ✅ Vĩnh viễn, always-on | Không có | Cần | Mạnh nhất, tự quản Docker + HTTPS + vá OS |
| Fly.io / Railway | ❌ Chỉ còn credit dùng thử | — | Cần | Không còn free tier thật |

**Khuyến nghị: Cloud Run.** Không chỉ vì free tier, mà vì `--ingress=internal` và
`--concurrency=1` là hai công cụ plan này dùng trực tiếp. HF Spaces nếu tuyệt đối
không muốn gắn thẻ — khi đó phải dựa vào `threading.Lock` và Space private.

**Đừng dựng cron ping giữ ấm.** Giữ ấm 24/7 cần ~2,6M vCPU-giây/tháng so với 180k
được miễn phí — tự biến free thành trả phí để tiết kiệm 10 giây. Trong một phiên
phân tích chỉ **lệnh gọi đầu tiên** chịu cold start.

**Mẹo chi phí:** `stateless_http=True` bỏ nhu cầu giữ SSE dài hạn → dùng được chế độ
Cloud Run *"CPU only during request"* thay vì *"CPU always allocated"*. Cùng một thay
đổi vừa sửa lỗi 1.3(a) vừa giảm chi phí.

---

## 2b. Tính di động — điều gì xảy ra nếu đổi warehouse

**Câu hỏi:** cho MCP public rồi sau đó phải đổi cloud khác thì có ảnh hưởng gì không?

**Trả lời: không ảnh hưởng tới phần MCP public.** Kiến trúc phân tầng:

```
claude.ai / điện thoại
      │   ← hợp đồng ổn định: URL connector + auth
   MCP server  (13 tool, tên và chữ ký không đổi)
      │   ← một chuỗi kết nối
   warehouse   ← chỗ DUY NHẤT thay đổi khi đổi cloud
```

Đổi warehouse = đổi **một chuỗi kết nối**. claude.ai không thấy gì: URL giữ nguyên, OAuth
giữ nguyên, connector trên điện thoại không phải cấu hình lại, skill Graham không đụng tới.

**Hệ quả:** công sức bỏ vào E3 (OAuth) **không mất đi khi migrate**. Không có rủi ro "đầu
tư 2 ngày rồi phải làm lại". Đây là lý do plan không cần tái cấu trúc vì trần lưu trữ.

### Ràng buộc kiến trúc mới: giữ phương ngữ DuckDB

Chi phí migrate phụ thuộc hoàn toàn vào một điều — có ở lại trong hệ DuckDB hay không:

| Đích đến | Phương ngữ SQL | `tools.py` (1.229 dòng) | Chi phí |
|---|---|---|---|
| **DuckDB file local trên VPS** | Giống hệt | Không đụng | **Thấp** |
| DuckDB file trên R2 / S3 | Giống hệt | Không đụng, **nhưng xem cảnh báo dưới** | Trung bình |
| Postgres / Neon / Supabase | Khác | Viết lại | Cao |
| ClickHouse / BigQuery | Khác | Viết lại | Cao |

**Quyết định: ở lại phương ngữ DuckDB.** Có chủ đích, không phải tình cờ — nó biến việc
đổi warehouse từ "viết lại 1.229 dòng SQL" thành "đổi một đường dẫn".

Mọi đề xuất đổi warehouse phải trả lời **hai** câu, không phải một:
1. *Có giữ được phương ngữ DuckDB không?* (chi phí viết lại)
2. *Có quota compute không?* (xem §2c — đây mới là ràng buộc đang siết)

> ⚠️ **Cảnh báo về R2/S3 — v3 xếp hạng sai.** `db.py` đặt `SET enable_external_access=false`
> làm **lớp bảo vệ số 2**, cố ý chặn `read_csv` / `read_text` / `glob` / **httpfs**. Nhưng để
> DuckDB đọc file database trên object storage thì **bắt buộc phải có httpfs** — nghĩa là
> migrate sang R2/S3 buộc phải **tắt đúng lớp bảo vệ đó**.
>
> Thêm nữa: file `.duckdb` qua httpfs chỉ **read-only** và mỗi truy vấn là một loạt HTTP
> range request; với truy vấn có join + percentile như trong `tools.py`, độ trễ tệ hơn rõ
> rệt. Parquet đọc từng phần tốt hơn file `.duckdb` nguyên khối — nhưng chuyển sang Parquet
> thì lại đụng `tools.py`, tức mất luôn ưu thế "không phải viết lại".
>
> Kết luận: object storage **không** phải lựa chọn rẻ nhất như v3 viết. File local trên
> VPS mới là lựa chọn giữ được cả ba lớp bảo mật.

---

## 2c. Trần lưu trữ MotherDuck — rủi ro cao hơn cả mảng E

**Tình trạng 25/08/2026: 8,6 / 10 GB free tier (86%).**

### Ràng buộc bị bỏ sót cho tới v4: **10 giờ compute/tháng**

Free tier MotherDuck là **10GB storage + 10 compute hours + 3 users**. v1–v3 chỉ nhìn
storage. Nhưng compute nhiều khả năng mới là thứ đang siết:

- Mỗi phiên hỏi từ điện thoại đánh thức duckling, chạy ~11 truy vấn, duckling còn sống
  thêm một lúc trước khi tự ngủ.
- **Cộng thêm** 6 GitHub Actions: daily build + weekly + monthly + `dbt build` toàn DAG.

Đây cũng là **lý do duy nhất khiến việc rời MotherDuck có ý nghĩa**: trần storage của R2
cũng là 10GB, nhưng R2 **không có quota compute** vì compute chạy trong container của bạn.

> ⚠️ **Chưa kiểm chứng.** Không đo được mức tiêu thụ compute (MotherDuck đang treo, và số
> này nằm ở dashboard chứ không truy vấn được). Comment trong `warehouse-monthly.yml` ghi
> job monthly mất **767 phút**, nhưng phần lớn là chờ vnstock ở 1 request/giây — **không
> phải** compute MotherDuck. **Việc cần làm đầu tiên: mở dashboard MotherDuck xem đã dùng
> bao nhiêu trong 10 giờ.** Nếu gần cạn, đó là nguyên nhân khả dĩ cho sự cố dưới đây —
> nhưng không khẳng định.

### So sánh ba đích đến theo ràng buộc thật

| | Storage | Compute | Giữ được `enable_external_access=false`? | Cold start |
|---|---|---|---|---|
| MotherDuck free | 10GB | **10 giờ/tháng** | ✅ | có |
| R2 + DuckDB | 10GB free, rồi $0,015/GB | không giới hạn | ❌ **phải tắt** | có |
| **Oracle Always Free VPS** | **200GB** | không giới hạn | ✅ | **không** |

Chi phí lưu trữ ở cả ba đều nhỏ đến mức vô nghĩa (25GB: MotherDuck ~$1,00/tháng, R2
~$0,23, Oracle $0). **Storage không phải vấn đề thật — compute mới là.**

Oracle Always Free: 200GB block storage (phần ARM đã bị cắt còn 2 OCPU/12GB trong 2026,
storage vẫn 200GB). Warehouse nằm trên **đĩa local** → không cần httpfs → giữ nguyên cả
ba lớp bảo mật, không round-trip mạng, không cold start, không quota compute. Với 8,6GB
hiện tại, 200GB là **gỡ hẳn ràng buộc** chứ không phải dời nó đi 1,4GB.

Đánh đổi thật: tự quản Docker, HTTPS, vá OS, backup. Oracle có tiếng thu hồi tài nguyên
always-free nhàn rỗi, đăng ký từ VN hay trục trặc.

Đây là rủi ro **độc lập với mảng E và cấp bách hơn**: nếu chạm trần, ingestion hằng ngày
hỏng → mọi thứ hỏng, public hay không cũng vậy. Ngược lại, nó **không** làm hỏng thiết kế
mảng E (xem §2b).

### Sự cố quan sát được ngày 25/08/2026

Khi đo thành phần dung lượng, MotherDuck không phản hồi:

```
SELECT 1 (không chạm catalog)  →  OK    (0,0s)   ← DuckDB tính local, không chứng minh gì
current_database()             →  LỖI  (60,0s)  ← round-trip tới server: treo
mọi truy vấn bảng              →  LỖI  (Catalog Error)
```

Kết nối và xác thực bình thường; phần compute/catalog phía server không phản hồi.
**Chưa quy được nguyên nhân** — có thể là sự cố nhất thời, duckling kẹt, hoặc liên quan
quota. Không kết luận vội.

### Đòn bẩy rẻ nhất: sửa bộ lọc sàn (nợ kỹ thuật đã biết)

`config/warehouse.yml` đã tự ghi nhận:

> *"danh sách này HIỆN KHÔNG ĐƯỢC THỰC THI... universe nạp vào `dim_symbols` thực tế là
> TOÀN BỘ ~1.598 mã cổ phiếu (bao gồm cả UPCOM), không dừng ở ~750 mã HOSE+HNX"*

Đang lưu **gấp đôi số mã so với ý định thiết kế**.

> ⚠️ **Giới hạn của suy luận này:** "gấp đôi" suy ra từ *số mã*, không phải *số byte đo
> được* — chưa đo được vì MotherDuck treo. BCTC chi tiết (8 năm × 3 loại × ~188 dòng)
> nhiều khả năng chiếm phần lớn dung lượng, và công ty UPCOM cũng nộp BCTC, nên suy luận
> hợp lý **nhưng chưa kiểm chứng**. Đo thật trước khi xoá bất cứ thứ gì.

### Việc cần làm (trước E2/E3 — hai bước tốn thời gian nhất)

- [ ] **Đo thật** khi MotherDuck sống lại: dung lượng theo bảng, và **tốc độ tăng/tuần**
      để biết còn bao nhiêu thời gian.
- [ ] Quyết định — đây là **quyết định của bạn**, không phải mặc định kỹ thuật:
      - **(a) Cắt phạm vi:** sửa bộ lọc sàn về HOSE+HNX. Rẻ nhất, giữ nguyên mọi thứ khác.
      - **(b) Phân tầng lưu trữ:** raw cũ ra Parquet trên R2, giữ mart trên MotherDuck.
      - **(c) Trả phí MotherDuck.** Nhanh nhất, tốn tiền định kỳ.
      - **(d) Migrate sang DuckDB file local trên VPS (Oracle Always Free).** Gỡ hẳn cả
        trần storage lẫn quota compute, giữ nguyên 3 lớp bảo mật. Đổi lại: tự vận hành.
      - **(e) Migrate sang DuckDB trên R2/S3.** ⚠️ Xem cảnh báo §2b — cũng trần 10GB, và
        buộc tắt `enable_external_access=false`. **Không khuyến nghị** trừ khi có lý do khác.
- [ ] **Kiểm tra mức dùng compute trên dashboard MotherDuck trước khi quyết định** — nếu
      compute mới là thứ cạn, thì (a)/(b)/(c) đều không cứu được, chỉ (d) mới cứu.
- [ ] Nếu chọn (a) hoặc (b): kiểm tra **mảng D và các job phụ thuộc** có giả định gì về
      universe đầy đủ không, trước khi cắt.

**Không chặn E0/E1** — hai bước đó rẻ và hữu ích dù chọn phương án nào.

---

## 3. Kế hoạch theo bước

### E0 — Read Scaling token + baseline

**Goal:** đóng lỗ hổng hàm scalar ở đúng tầng, và có mốc so sánh trước khi sửa code.

> **Thuộc tính cần đạt (viết theo mục tiêu, không theo cơ chế):** MCP server phải dùng
> **credential chỉ-đọc, đặc quyền tối thiểu, được cưỡng chế ở phía server** — không phụ
> thuộc rào chắn ứng dụng hay cờ client.
>
> Trên MotherDuck, cơ chế hiện thực là **Read Scaling token**. Nếu sau này đổi warehouse
> (xem §2b/§2c), **thuộc tính này phải được giữ bằng cơ chế tương đương** — R2/S3: khoá
> IAM chỉ-đọc; Postgres: role read-only. Đừng migrate rồi đánh rơi nó.

**Tasks:**
- [ ] Tạo **Read Scaling token** trên MotherDuck (loại token: Read Scaling, không phải Read/Write).
- [ ] Kiểm chứng token: connect `md:vn_market`, chạy một `SELECT` (phải chạy được),
      rồi thử một thao tác ghi (phải bị từ chối).
- [ ] **Ràng buộc:** database không thể *attach* bằng read scaling token — `vn_market`
      phải đã được attach sẵn bằng token read/write. Xác minh trước khi đổi.
- [ ] Ghi lại **baseline**: chạy `python -m pytest tests/ -q` (129 test) và lưu kết
      quả 3 tool (`get_stock_profile`, `get_financial_statement`, `run_sql`) qua stdio
      để so sánh sau E1.
- [ ] Token cũ (read/write) **giữ nguyên** cho GitHub Actions — chỉ MCP server dùng token mới.

**Acceptance:** MCP server local chạy được với read scaling token; thao tác ghi bị
MotherDuck từ chối; 129 test pass; có file baseline để đối chiếu.

**Lưu ý:** replica read scaling **eventually consistent, trễ vài phút**. Không ảnh
hưởng vì warehouse cập nhật theo ngày. Lợi ích kèm theo: tách read traffic khỏi
write traffic của GitHub Actions.

**Human-only:** tạo token trên MotherDuck UI.

---

### E1 — Transport HTTP + sửa tương tranh + cấu hình bảo mật transport

**Goal:** server chạy qua HTTP ở local, đúng cấu hình cho serverless.

**Tasks:**
- [ ] `FastMCP(...)` constructor: thêm `stateless_http=True`, cân nhắc `json_response=True`,
      `host="0.0.0.0"`, `port=int(os.getenv("PORT", 8080))`.
      **Không** đặt `stateless_http` ở `mcp.run()` — signature không nhận.
- [ ] Cấu hình `transport_security=TransportSecuritySettings(allowed_hosts=[...],
      allowed_origins=[...])` cho domain sẽ deploy. Để rỗng = tự chặn mình.
- [ ] `mcp.run(transport="streamable-http")`.
- [ ] `db.py`: `threading.Lock` quanh `run_query` (xem 1.1).
- [ ] Thêm **hai** endpoint, không cần auth, **tách bạch vai trò**:
      - `/health` — **liveness**: tiến trình còn sống. Chỉ dùng cho nền tảng quyết định restart.
        Không chạm warehouse.
      - `/ready` — **readiness**: chạy một truy vấn rẻ (`SELECT 1 FROM dim_stock LIMIT 1`)
        để xác nhận warehouse với tới được. Dùng cho **bạn** chẩn đoán.
      > Vì sao phải tách: sự cố MotherDuck ngày 25/08/2026 cho thấy nếu gộp, `/health` báo
      > 200 trong khi mọi tool đều lỗi — trên điện thoại chỉ thấy timeout khó hiểu. Ngược
      > lại, nếu `/health` kiểm cả warehouse thì một sự cố phía MotherDuck sẽ khiến nền
      > tảng restart container vô ích mà không sửa được gì.
- [ ] Tool trả **thông báo lỗi rõ ràng** khi warehouse không với tới được, thay vì để timeout thô.
- [ ] Test local qua HTTP: gọi ≥3 tool, đối chiếu với baseline E0.
- [ ] Test đồng thời: bắn 5 request song song, không được có lỗi interrupt.
- [ ] Chạy lại 129 test.

**Acceptance:** 3 tool trả kết quả **khớp baseline E0**; 5 request đồng thời không lỗi;
129 test pass.

**Không đổi:** logic 13 tool, `tools.py`, rào chắn SQL. Đây là thay đổi transport thuần.

---

### E2 — Docker + deploy với ingress hạn chế

**Goal:** server chạy trên nền tảng, **chưa mở ra internet**.

**Tasks:**
- [ ] `Dockerfile` (python:3.12-slim, cài `requirements.txt`, chạy `mcp_server.server`).
      Không COPY `.env`.
- [ ] `.dockerignore`: `.venv`, `data/`, `.git`, `__pycache__`, `.env`, `docs/`.
- [ ] Không đưa `data/warehouse.duckdb` vào image — server chỉ đọc MotherDuck.
- [ ] Secret qua secret manager của nền tảng: `motherduck_token` (**read scaling token
      từ E0**), `WAREHOUSE_DB=md:vn_market`.
- [ ] Deploy **Cloud Run với `--ingress=internal`** (hoặc HF Space **private**).
- [ ] Đặt `--concurrency=1` và chế độ *CPU only during request*.
- [ ] Xác minh `/health` qua đường nội bộ; kiểm log thấy kết nối MotherDuck thành công.
- [ ] Cập nhật `allowed_hosts` ở E1 bằng domain thật vừa nhận được, deploy lại.

**Acceptance:** `/health` trả 200 qua đường nội bộ; **truy cập từ internet công khai
bị từ chối**; log không có lỗi DNS rebinding.

**Human-only:** tạo tài khoản hosting; nạp secret.

> Khác v1: kết thúc E2 server **chưa** public. Không còn cửa sổ chạy public không auth.

---

### E3 — Xác thực (rủi ro tiến độ lớn nhất — ước lượng 1–2 ngày, không phải 2–4h)

**Goal:** chỉ mình bạn gọi được server.

Bối cảnh: repo dùng `mcp.server.fastmcp` (SDK chính thức 1.29.0), có sẵn
`token_verifier` / `auth` / `auth_server_provider`. Server đóng vai **OAuth 2.1
Resource Server** — không phải tự viết Authorization Server.

**Nhưng v1 bỏ sót một nửa:** MCP spec (2025-11-25) yêu cầu server **MUST** implement
**OAuth 2.0 Protected Resource Metadata (RFC9728)** — expose
`/.well-known/oauth-protected-resource` để client discover được AS. Không có nó,
luồng OAuth không khởi động. Spec cũng **SHOULD** hỗ trợ Dynamic Client Registration;
claude.ai có ô Client ID/Secret nên static credentials dùng được, nhưng phải chọn AS
hỗ trợ đúng luồng.

**Tasks:**
- [ ] Chọn AS có free tier (Auth0 / Descope / Clerk); tạo application; lấy Client ID + Secret.
- [ ] Cấu hình `token_verifier` + `auth` trong FastMCP để xác thực JWT.
- [ ] **Expose PRM endpoint** `/.well-known/oauth-protected-resource`.
- [ ] Xác minh bằng `curl`: request **không** token → bị từ chối; có token hợp lệ → qua.
- [ ] Xác minh PRM: `curl https://<host>/.well-known/oauth-protected-resource` trả metadata đúng.

**Acceptance:** request không token bị chặn; PRM endpoint trả metadata hợp lệ.

**Human-only:** tạo tài khoản AS.

#### Mốc bỏ cuộc — đặt trước, đừng quyết lúc đang mệt

Nếu sau **2 ngày** E3 chưa xong, chuyển sang **`static_headers`** (beta của Anthropic):
admin nhập một header cố định (API key/bearer token) một lần, Claude gửi kèm mọi
request. Phải **liên hệ Anthropic support** để bật cho tổ chức của bạn.

> **v1 đề xuất đặt bí mật trong đường dẫn URL — v2 rút lại.** Tài liệu Anthropic nói
> rõ credential trong URL (`?token=`, `?apiKey=`) **không được khuyến nghị**: URL bị
> ghi vào server log, proxy và lịch sử duyệt. Cảnh báo ở v1 không đủ mạnh so với mức
> độ thật. Dùng `static_headers`, không dùng URL.

Rủi ro của đường lui này thấp hơn v1 nhiều **vì E0 đã đóng lỗ hổng hàm scalar** —
kể cả khi lớp auth yếu hơn dự kiến, token chỉ-đọc vẫn chặn mọi thao tác ghi/admin.

---

### E3.5 — Mở public

**Goal:** chỉ làm sau khi E3 đã xác minh.

**Tasks:**
- [ ] Cloud Run: đổi `--ingress=all` (hoặc HF: Space → public nếu cần).
- [ ] Xác minh lại ngay: `curl` không token → bị từ chối.
- [ ] **Ghi sẵn lệnh tắt khẩn cấp vào doc này** (mục 5) và thử một lần cho chắc.

**Acceptance:** URL public tồn tại; truy cập không auth bị từ chối; đã thử tắt khẩn
cấp thành công một lần.

---

### E4 — Skill Graham lên claude.ai + kết nối

**Goal:** claude.ai/điện thoại chạy đúng khung Graham, không phải kiến thức chung.

**Tasks:**
- [ ] Zip `.claude/skills/graham-fundamental-analysis/` — ZIP phải chứa **folder** có
      `SKILL.md` bên trong, không zip trực tiếp file.
- [ ] Bật **code execution** trong claude.ai (bắt buộc để dùng Skills) — skill có số
      học (NCAV, số Graham, độ phân tán) cần nó.
- [ ] Upload ở `Customize > Skills`.
- [ ] Rà nội dung skill: câu kiểu *"trong repo này"*, *"dùng Bash"* nên đổi cho khớp
      môi trường claude.ai. Phần lớn không cần sửa.
- [ ] Thêm connector: `Customize > Connectors > + > Add custom connector`, nhập URL +
      OAuth Client ID/Secret (hoặc `static_headers`).
- [ ] Bật connector trong cuộc hội thoại.

**Acceptance:** hỏi *"phân tích cổ phiếu REE"* trên claude.ai web → skill kích hoạt,
gọi được tool warehouse, ra báo cáo có `as_of` và `peer_basis`.

---

### E5 — Nghiệm thu từ điện thoại + đo hạn mức thật

**Goal:** xác nhận mục tiêu ban đầu đạt được, và biết Pro chịu được bao nhiêu.

**Tasks:**
- [ ] Mở app Claude trên điện thoại, xác nhận connector **tự sync** từ web (app điện
      thoại không tự thêm server mới được — phải thêm từ web trước).
- [ ] Chạy trọn một bài phân tích từ điện thoại.
- [ ] Đo: một cửa sổ 5 giờ chạy được bao nhiêu bài trước khi chạm hạn mức.
- [ ] Đo cold start thực tế của lệnh gọi đầu tiên.
- [ ] Ghi số đo vào `docs/E-ket-qua-va-no-ky-thuat.md` theo quy ước các mảng trước.

**Acceptance:** hoàn tất một bài phân tích đầy đủ từ điện thoại, không đụng máy Mac.

---

## 4. Mảng F (sau khi có số đo E5) — tối ưu token

**Chỉ làm sau khi E5 cho số thật.** Đừng tối ưu trước khi biết hạn mức có phải vấn đề không.

Số đo từ phiên Claude Code 24/08/2026 (một bài phân tích REE):
- Payload warehouse ~36.900 token = ~14% tổng chi phí phiên
- `get_financial_statement` chiếm **71%** phần đó (3 lượt gọi, ~26.000 token)
- **50/188 dòng (27%) toàn số 0 ở cả 8 kỳ** = ~3.500 token lãng phí mỗi lượt gọi

**Việc dự kiến:**
- [ ] `get_financial_statement`: thêm `drop_empty_rows=True` (mặc định bật). Cắt ~21%
      payload của tool nặng nhất.
- [ ] Thêm `get_graham_bundle(symbol)`: gộp ~11 lượt gọi còn 1, tính sẵn bằng SQL trong
      DuckDB **từ dòng BCTC gốc** (NCAV, vốn lưu động, bao phủ lãi vay theo năm,
      trung bình/độ phân tán 8 năm). Vẫn tuân thủ luật trong skill: tính từ dòng gốc,
      không từ marts suy ra.
- [ ] Viết dbt test cho các chỉ tiêu tính sẵn đó.

**Vì sao đáng làm ngoài chuyện token:** đẩy số học vào warehouse biến logic phân tích
thành thứ **có version, có test, có lineage**, thay vì phụ thuộc vào việc mô hình tính
đúng trong từng cuộc hội thoại. Đây là câu trả lời đúng về mặt Data Engineering.

---

## 5. Cách tắt khẩn cấp

Ghi ra đây để lúc cần không phải tra cứu. **Thử một lần ở E3.5 cho chắc.**

- **Cloud Run:** `gcloud run services update <service> --ingress=internal --region=<region>`
- **Hugging Face:** Space Settings → đổi visibility sang **private**
- **Chặn tận gốc (cả hai):** thu hồi **read scaling token** trên MotherDuck UI →
  server còn sống nhưng không đọc được gì. Đây là nút tắt chắc chắn nhất, và nó chỉ
  tồn tại nhờ E0.

## 6. Ràng buộc & lưu ý

- **Không sửa `tools.py`** trong mảng E. E chỉ đụng transport, tương tranh, đóng gói,
  xác thực. Đổi hành vi tool để sang mảng F.
- **Không commit secret.** Token chỉ đi qua secret manager của nền tảng. `.env` đã
  trong `.gitignore` — kiểm tra lại trước khi push.
- **Giữ nguyên luồng Claude Code local.** `.mcp.json` (stdio) và bản remote chạy song
  song được, cùng đọc một warehouse. Không phải chọn một.
- **Không đụng pipeline dữ liệu.** 6 workflow đang chạy tốt; GitHub Actions vẫn dùng
  token read/write cũ.
- **Giữ phương ngữ DuckDB** (§2b). Mọi đề xuất đổi warehouse phải trả lời được câu hỏi
  này trước — nó là ranh giới giữa "đổi một đường dẫn" và "viết lại 1.229 dòng SQL".
- **Credential của MCP server luôn là chỉ-đọc, đặc quyền tối thiểu** (§E0) — kể cả sau
  khi đổi warehouse. Đây là thuộc tính phải giữ, không phải một bước làm một lần.
- Dừng và báo cáo cuối mảng theo quy ước `docs/<mảng>-ket-qua-va-no-ky-thuat.md`.

## 7. Human-only tasks (tổng hợp)

- [ ] (E0) Tạo **Read Scaling token** trên MotherDuck.
- [ ] (E2) Tạo tài khoản hosting (Cloud Run hoặc Hugging Face); nạp secret.
- [ ] (E3) Tạo tài khoản Authorization Server; lấy Client ID + Secret.
- [ ] (E3, nếu dùng đường lui) Liên hệ **Anthropic support** xin bật `static_headers`.
- [ ] (E4) Bật code execution; upload ZIP skill ở `claude.ai > Customize > Skills`.
- [ ] (E4) Nhập URL + credential vào `claude.ai > Customize > Connectors`.
- [ ] (E5) Kiểm thử từ điện thoại.

## 8. Khái niệm DE chạm tới ở mảng này

Containerisation · service deployment & scale-to-zero · secret management ·
**least-privilege credentials (read scaling token)** · connection pooling và an toàn
luồng · **stateless service design** · phân tầng bảo mật (defense in depth) ·
OAuth 2.1 resource server + protected resource metadata · tách control plane khỏi
data plane · **tách read replica khỏi write primary**.

## 9. Nguồn đã đối chiếu

- [Authorization — MCP spec 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization) — PRM là MUST, DCR là SHOULD
- [Authentication for connectors — Claude.ai Docs](https://claude.com/docs/connectors/building/authentication) — `static_headers` beta; cảnh báo credential trong URL
- [HTTP Deployment — FastMCP](https://gofastmcp.com/deployment/http) — stateless cho serverless/multi-replica
- [Session Management — python-sdk #1180](https://github.com/modelcontextprotocol/python-sdk/issues/1180)
- [Read Scaling — MotherDuck Docs](https://motherduck.com/docs/key-tasks/authenticating-and-connecting-to-motherduck/read-scaling/) — chỉ SELECT, chặn write/admin; ràng buộc attach
- [Get started with custom connectors using remote MCP — Anthropic](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)
