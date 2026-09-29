# Alert và Runbook

Mỗi alert dựa trên triệu chứng người dùng hoặc SLO, không dựa trực tiếp vào tên implementation nội bộ. Ngưỡng lấy từ [`../config/slo.yaml`](../config/slo.yaml) và baseline đo ngày 2026-09-29 (P95 bình thường 1221 ms, cost trung bình ~$0.002/request, error rate 0%). Rule đầy đủ ở [`../config/alert_rules.yaml`](../config/alert_rules.yaml).

## Alert 1

- Tên: `latency_p95_degraded`
- Severity: P2-warning
- Duration: 5m
- Kênh thông báo: Slack `#day13-llmops-alerts`
- SLI/SLO liên quan: `fast_successful_requests` (99.5% request ≤ 3000 ms trong 28 ngày). Đây là cảnh báo sớm: 2000 ms ≈ 1.6x P95 bình thường, vẫn dưới SLO 3000 ms.
- Điều kiện và thời gian duy trì: P95 `latency_ms` của `response_sent` trong cửa sổ 5 phút > 2000 ms, kéo dài 5 phút.
- Ảnh hưởng tới người dùng: câu trả lời chậm rõ rệt. Vì agent chạy đồng bộ trong endpoint async, khi một request chậm thì các request đồng thời phải xếp hàng. Trong lần thử `rag_slow`, server đo ~2650 ms nhưng client chờ 10–13 s.
- Ba bước kiểm tra đầu tiên:
  1. Dashboard panel *Latency percentiles and TTFT*: nếu P95 tăng mà TTFT P95 vẫn ~50 ms thì chậm nằm trước bước generation (retrieval hoặc fetch prompt).
  2. Lọc `data/logs.jsonl` với `event == "response_sent" and latency_ms > 2000` trong khoảng alert, lấy vài `correlation_id`.
  3. Mở trace có cùng `correlation_id` trên Langfuse, so thời lượng span `retrieval` với `llm-generation`.
- Mitigation tạm thời: nếu span `retrieval` chậm thì tắt hoặc chuyển vector store dự phòng, giảm concurrency đầu vào; nếu chậm do fetch prompt thì kiểm tra Langfuse status (app có fallback local sau timeout 2 s).
- Owner: Tran Duc Quan (on-call)

## Alert 2

- Tên: `error_rate_high`
- Severity: P1-critical
- Duration: 5m
- Kênh thông báo: Slack `#day13-llmops-alerts`
- SLI/SLO liên quan: guardrail `error_rate_pct_max: 2` và SLO `fast_successful_requests` (request lỗi là bad event, đốt error budget trực tiếp).
- Điều kiện và thời gian duy trì: `count(request_failed) / count(request_received) * 100` trong 5 phút > 2%, kéo dài 5 phút. Ở mức 2%, burn rate = 4x, nếu kéo dài sẽ hết budget 28 ngày trong 7 ngày.
- Ảnh hưởng tới người dùng: người dùng nhận HTTP 500, không có câu trả lời.
- Ba bước kiểm tra đầu tiên:
  1. Dashboard panel *Error rate and retrieval success*: xem breakdown `error_type` và retrieval success rate (guardrail ≥ 90%).
  2. Lọc log `event == "request_failed"`, đọc `error_type`, `payload.detail`, lấy `correlation_id`.
  3. Mở trace tương ứng; span có `level = ERROR` và `statusMessage` cho biết bước lỗi (ví dụ `retrieval: RuntimeError: Vector store timeout`).
- Mitigation tạm thời: nếu lỗi ở retrieval thì bật fallback trả lời không có context hoặc rollback thay đổi gần nhất; nếu lỗi sau khi đổi prompt thì rollback label `production` (`python scripts/prompt_labels.py promote <version cũ>`). SDK cache prompt 60 s (`cache_ttl_seconds=60`), nên rollback cần tối đa khoảng 1 phút mới có hiệu lực trên mọi instance; cần rollback ngay thì restart API.
- Owner: Tran Duc Quan (on-call)

## Alert 3

- Tên: `cost_burn_high`
- Severity: P2-warning
- Duration: 15m
- Kênh thông báo: Slack `#day13-llmops-alerts`
- SLI/SLO liên quan: guardrail `daily_cost_usd_max: 2.5`.
- Điều kiện và thời gian duy trì: chi phí 1 giờ gần nhất × 24 (dự báo chi phí ngày) > $2.5, kéo dài 15 phút. Duration dài hơn hai alert trên vì cost không làm hỏng trải nghiệm ngay, tránh cảnh báo vì một đợt traffic ngắn.
- Ảnh hưởng tới người dùng: không ảnh hưởng trực tiếp tới câu trả lời, nhưng vượt ngân sách buộc phải hạ cấp hoặc chặn dịch vụ.
- Ba bước kiểm tra đầu tiên:
  1. Dashboard panel *Cost over time* và *Input and output tokens*: cost tăng do traffic (panel Traffic tăng theo) hay do token/request tăng.
  2. Nếu `tokens_out` mỗi request tăng: lọc log `response_sent` có `tokens_out` cao, lấy `correlation_id`.
  3. Mở trace, xem generation: `usageDetails`, `costDetails`, và prompt name/version đang dùng (prompt mới có làm câu trả lời dài hơn không).
- Mitigation tạm thời: rollback prompt `production` về version trước, giới hạn `max_tokens` output, rate-limit user/session có traffic bất thường.
- Owner: Tran Duc Quan (on-call)
