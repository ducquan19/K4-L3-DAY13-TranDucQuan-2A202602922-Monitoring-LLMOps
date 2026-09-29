# Báo cáo cá nhân — K4-L3A Day 13 Monitoring & LLMOps

> Mỗi học viên hoàn thiện một file duy nhất này. Khi dẫn evidence, dùng đường dẫn tương đối, ví dụ `evidence/07-trace-waterfall.png`.

## 1. Thông tin học viên

- **Họ và tên:** Trần Đức Quân
- **MSSV:** 2A202602922
- **Lớp:** K4-L3A
- **Repository URL:** [GitHub URL](https://github.com/ducquan19/K4-L3-DAY13-TranDucQuan-2A202602922-Monitoring-LLMOps)
- **Commit SHA cuối:** `e9c741147698308622201430959ca553dc63db5e`. Đây là commit chứa toàn bộ code, report và evidence; commit ngay sau nó chỉ điền dòng này.
- **Challenge ID:** day13-k4-l3a-monitoring-llmops-v1
- **Tên project Langfuse cá nhân:** `day13-k4-l3a-2A202602922`

## 2. Evidence index

Điền đúng đường dẫn tới evidence thực tế. Có thể đổi tên hoặc dùng nhiều ảnh nếu cần.

| Evidence | Đường dẫn |
|---|---|
| Pytest cuối | `evidence/01-pytest.txt` |
| Log validator | `evidence/02-log-validator.txt` |
| Dashboard validator | `evidence/03-dashboard-validator.txt` |
| Structured log | `evidence/04-structured-log.txt` |
| PII redaction | `evidence/05-pii-redaction.txt` |
| Trace list | `evidence/06-trace-list.png` |
| Trace waterfall | `evidence/07-trace-waterfall.png` |
| Trace metadata | `evidence/08-trace-metadata.png` |
| Prompt versions | `evidence/09-prompt-versions.png`, nội dung/labels: `evidence/09-prompt-versions.txt` |
| Prompt rollback | `evidence/10-prompt-rollback.png`, log promote/rollback + trace IDs: `evidence/10-prompt-rollback.txt` |
| Dashboard runtime | `evidence/11-dashboard-overview.png`, số liệu: `evidence/11-dashboard-summary.txt` |
| Incident metric | `evidence/12-incident-metric.png`, số liệu: `evidence/12-incident-metric.txt` |
| Incident log | `evidence/13-incident-log.txt` |
| Kiểm chứng fix | `evidence/15-incident-fix-verification.txt` |
| Incident trace | `evidence/14-incident-trace.png` (trace `4e7c4306…`), số liệu: `evidence/14-incident-trace.txt` |

## 3. Kết quả kỹ thuật

| Nội dung | Baseline | Kết quả cuối | Nhận xét |
|---|---|---|---|
| `validate_logs.py` | 30/100 | 100/100 (CP4) | Baseline: 42 records, 40 thiếu required fields/enrichment, 0 correlation ID (`evidence/00-baseline-log-validator.txt`). CP4: 740 records, 362 correlation ID, 0 thiếu field, 0 PII (`evidence/02-log-validator.txt`) |
| `validate_dashboard.py` | 6/6 panel (contract) | 6/6 panel (CP4) | Contract không đổi; dashboard runtime dựng bằng `scripts/build_dashboard.py`. Xem `evidence/03-dashboard-validator.txt` |
| `pytest` | 22 passed | 35 passed (CP4) | CP1 thêm 8 test PII/correlation ID/rò context; CP2 thêm 4 test child observation, span lỗi và dashboard builder; CP4 thêm 1 test hồi quy cho traffic rate. Xem `evidence/01-pytest.txt` |
| Số traces hợp lệ | 20 requests, chỉ root observation | 348 request (CP2), mỗi trace có root + retrieval + generation | Baseline chưa có child span, token/cost trên Langfuse = 0 |
| Số PII leak | 0 | 0 (CP1) | Input mẫu có email, SĐT, số thẻ; log chỉ còn `[REDACTED_*]`. Xem `evidence/05-pii-redaction.txt` |
| Latency P95 / TTFT P95 | 1134 ms / 50 ms | Bình thường 153 ms / 50 ms; khi `rag_slow` 2654 ms / 50 ms | Baseline tính từ `evidence/00-baseline-logs.jsonl`; CP2 là P95 theo phút trên dashboard |
| Retrieval success rate | 100% (20/20) | 100% (CP2) | Chưa bật `tool_fail` |

> Baseline CP0 đo lúc 2026-09-29 14:17 (+07), commit `13b6066`, trên `data/logs.jsonl` sau khi chạy `load_test.py`.

## 4. Logging và PII

- **Cách tạo/nhận và truyền correlation ID:** `CorrelationIdMiddleware` ([app/middleware.py](../app/middleware.py)) gọi `clear_contextvars()` đầu mỗi request, nhận header `x-request-id` nếu đúng format `req-<8-hex>`; nếu thiếu hoặc sai format (tránh giả mạo hoặc chèn ký tự xuống dòng vào log) thì sinh ID mới từ `uuid4`. ID được `bind_contextvars` vào structlog, lưu ở `request.state`, truyền vào `LabAgent.run` (metadata trace Langfuse), trả lại trong body `correlation_id` và header `x-request-id`, kèm `x-response-time-ms`. Context được clear lại sau `call_next` để không rò sang request sau.
- **Các metadata được ghi vào structured log:** `ts`, `level`, `service`, `event`, `correlation_id`, `env`, `model`, `feature`, `session_id`, `user_id_hash` (SHA-256 cắt 12 ký tự, không ghi user_id gốc), cùng latency, TTFT, token, cost, quality và tool success ở event `response_sent`.
- **Cách bảo đảm PII được scrub trước khi ghi:** `scrub_event` được đăng ký trong chuỗi processor của structlog ([app/logging_config.py](../app/logging_config.py)), sau `format_exc_info` (nên traceback cũng được scrub) và trước `JsonlFileProcessor`/`JSONRenderer`. Processor scrub đệ quy mọi giá trị string, kể cả dict/list lồng nhau trong `payload`, trừ các field do hệ thống sinh (`ts`, `level`, `correlation_id`, `user_id_hash`). [app/pii.py](../app/pii.py) có pattern email, thẻ tín dụng, CCCD 12 số, SĐT Việt Nam và hộ chiếu (`[A-Z]\d{7}`). Pattern thẻ chạy trước CCCD/SĐT để không bị khớp một phần.
- **Cách kiểm chứng kết quả:** xóa log baseline (bản sao đã lưu ở `evidence/00-baseline-logs.jsonl`), chạy `load_test.py` rồi `validate_logs.py` được 100/100. Grep regex PII trên `data/logs.jsonl` trả 0 dòng. Test mới trong [tests/test_pii.py](../tests/test_pii.py) và [tests/test_correlation_logging.py](../tests/test_correlation_logging.py) kiểm tra: sinh hoặc giữ request ID, từ chối ID sai format, hai request liên tiếp có correlation ID và session riêng (không rò context), email không xuất hiện trong file log.

## 5. Tracing và prompt versioning

- **Cách xác nhận traces do chính tôi tạo trong project cá nhân:** `.env` dùng key của project `day13-k4-l3a-2A202602922` (org "Duc's Organization"). Trace sinh từ `load_test.py` và các request thử prompt tôi tự gửi với `x-request-id` cố định (`req-b1000001`, `req-c2000002`, `req-a2000003`, `req-a1000004`). Ngoài UI, tôi truy vấn `GET /api/public/v2/observations` bằng key của project để đối chiếu: trace trả về có đúng `correlation_id` đã gửi.
- **Cấu trúc root/retrieval/generation observations:** root `lab-agent-run` (type AGENT, decorator `@observe`) có hai child tạo bằng `start_as_current_observation` của SDK v4 ([app/agent.py](../app/agent.py)):
  - `retrieval` (RETRIEVER): input là query đã scrub PII, output `doc_count`. Nếu retrieval lỗi thì span được đánh `level=ERROR` kèm `status_message`.
  - `llm-generation` (GENERATION): gắn `model`, `prompt` (link tới prompt Langfuse), `usage_details` (input/output tokens), `cost_details` (input/output/total USD) và `completion_start_time` = start + TTFT. Input/output chỉ là preview đã scrub, vì prompt đã compile chứa nguyên câu hỏi của người dùng.
- **Cách nối trace với log:** `correlation_id` nằm trong trace metadata (qua `propagate_attributes`) và trong mọi dòng log của request. Từ log chậm hoặc lỗi, lấy `correlation_id` rồi lọc metadata trên Langfuse để ra trace, và ngược lại.
- **Prompt name:** `day13-chat` (text prompt, giữ ba biến `{{feature}}`, `{{docs}}`, `{{message}}`), tạo bằng [scripts/prompt_labels.py](../scripts/prompt_labels.py) `setup`.
- **Version/label baseline:** v1, labels `baseline` + `production`, là template gốc của lab.
- **Version/label candidate:** v2, label `candidate`, thêm dòng "Answer in at most 3 short bullet points, using only the docs below." Prompt dài hơn nên `tokens_in` của cùng input tăng từ 32 lên 49.
- **Trace ID của mỗi version:** cùng input "Explain why metrics traces and logs work together" (`evidence/10-prompt-rollback.txt`):

  | correlation_id | Label | Version | Trace ID |
  |---|---|---|---|
  | `req-b1000001` | baseline | v1 | `f9f084e706d0528a45026e01b1798592` |
  | `req-c2000002` | candidate | v2 | `c3b3b13d4e57c3044609e5127b1ce916` |
  | `req-a2000003` | production (sau promote) | v2 | `7b97aae167a9df14888e761a2a1b0ad5` |
  | `req-a1000004` | production (sau rollback) | v1 | `90c0ccc991ec1043ef7288646fda39fe` |

- **Cách promote và rollback `production`:** `python scripts/prompt_labels.py promote 2` gọi `update_prompt(new_labels=["production"])`; Langfuse chỉ cho một version giữ mỗi label, nên label tự chuyển khỏi v1. Rollback bằng `promote 1`. App đọc prompt theo label, không theo số version, nên rollback không cần deploy lại code. SDK cache prompt 60 giây (`cache_ttl_seconds=60`), nên request trong vòng 1 phút sau khi đổi label có thể vẫn dùng version cũ. Khi thử, tôi gửi request qua một instance API mới khởi động để loại bỏ cache.

## 6. Dashboard, SLO và alerts

- **Dashboard và sáu panel:** [scripts/build_dashboard.py](../scripts/build_dashboard.py) đọc `data/logs.jsonl` và `config/dashboard.yaml` (dùng lại hàm kiểm tra của validator), rồi sinh `data/dashboard.html`.
  - Trang có 6 panel đúng tên, event, aggregation và unit của contract; time range 60 phút; tự reload mỗi 30 giây (`--watch` để dựng lại liên tục).
  - Mỗi panel có badge OK/BREACH theo threshold. Panel latency, traffic, errors và quality vẽ đường threshold nét đứt. Cost và tokens có ngưỡng trên tổng cả cửa sổ nên chỉ thể hiện bằng badge. Panel latency có TTFT P95; panel errors có breakdown `error_type` và retrieval success.
  - Kiểm tra runtime: chạy workload trải đều 14:47–14:53 (+07), bật `rag_slow` từ 14:49:47 đến khoảng 14:52. P95 theo phút tăng từ khoảng 153 ms lên 2654 ms trong các phút 14:49–14:51, rồi về 154 ms sau khi tắt. TTFT P95 giữ nguyên 50 ms, cho thấy phần chậm nằm trước bước generation.
  - Cửa sổ 13:54–14:54 có 713 records: P95 2654 ms (OK), traffic 11.6 req/phút, error 0%, cost $0.70, quality 0.88. Tokens 56,170 vượt ngưỡng 50,000 (BREACH). Đây là tín hiệu thật: workload thử dày hơn nhiều so với giả định của contract (khoảng 350 request trong 7 phút), nên tôi giữ nguyên threshold.
- **SLO và lý do chọn:** giữ `fast_successful_requests`: 99.5% request trả `response_sent` trong ≤ 3000 ms, cửa sổ 28 ngày ([config/slo.yaml](../config/slo.yaml)).
  - Baseline 44 request bình thường: P50 152 ms, P95 1221 ms, P99 2089 ms. P99 cao do lần fetch prompt đầu tiên sau khi khởi động. Ngưỡng 3000 ms có headroom khoảng 2.5x so với P95, không cảnh báo giả khi cold start, và trùng threshold của panel latency trong dashboard contract.
  - Target 99.5% thay vì 99.9% vì prompt fetch (Langfuse) và retrieval là dependency ngoài.
  - Điểm yếu đã quan sát: `rag_slow` đẩy mọi request lên khoảng 2650 ms. Mức này vẫn trong SLO nhưng gấp đôi P95 bình thường, nên tôi thêm alert cảnh báo sớm ở 2000 ms.
- **Cách tính error budget:** budget = 100% − 99.5% = 0.5% request xấu (lỗi hoặc > 3000 ms) trong 28 ngày.
  - Với workload lab khoảng 2.4 request/phút: 2.4 × 60 × 24 × 28 ≈ 96,768 request, tức được phép khoảng 484 request xấu.
  - Burn rate = tỉ lệ xấu thực tế / 0.5%. Error rate 2% (ngưỡng alert 2) tương ứng burn rate 4x, sẽ hết budget 28 ngày trong 7 ngày.
- **Ba alert và runbook tương ứng:** ([config/alert_rules.yaml](../config/alert_rules.yaml), runbook trong [docs/alerts.md](../docs/alerts.md)). Cả ba đều gửi Slack `#day13-llmops-alerts`, owner là tôi (on-call). Mỗi alert ứng với một kiểu sự cố thực hành: chậm (`rag_slow`), lỗi (`tool_fail`), chi phí (`cost_spike`).

  | Alert | Severity | Điều kiện | Duration |
  |---|---|---|---|
  | `latency_p95_degraded` | P2-warning | P95 latency > 2000 ms | 5m |
  | `error_rate_high` | P1-critical | error rate > 2% | 5m |
  | `cost_burn_high` | P2-warning | chi phí 1h × 24 > $2.5 | 15m |

  Duration của alert cost dài hơn vì cost không làm hỏng trải nghiệm ngay, và để tránh báo động vì một đợt traffic ngắn.

## 7. Điều tra challenge

- **Challenge ID:** day13-k4-l3a-monitoring-llmops-v1
- **Khoảng thời gian điều tra:** 2026-09-29 16:16:51–16:17:15 (+07), tức 09:16:51–09:17:15 UTC. Bắt đầu từ log `incident_enabled` (`req-9fa51ac5`), kết thúc ở response challenge cuối cùng. Dashboard dựng với time range 60 phút, 15:19–16:19.
- **Triệu chứng từ metrics:** (`evidence/12-incident-metric.txt`)
  - Panel latency: P95 **3832 ms**, vượt ngưỡng 3000 ms (BREACH). Cả 5/5 request challenge vượt `latency_threshold_ms` 2000 ms (thấp nhất 2652 ms), trong khi P95 lúc bình thường ở CP2 là **152 ms** (gấp khoảng 17–25 lần).
  - TTFT P95 giữ nguyên **50 ms**, error rate 0%, retrieval success 100%, cost và quality bình thường. Kết luận từ metric: hệ thống chậm chứ không lỗi, và phần chậm nằm trước bước sinh token.
  - Panel traffic 5.0 req/phút (OK): chỉ 5 request trong khoảng 15 giây, thấp hơn mức 11.6 req/phút ở CP2, nên độ chậm không do tải tăng.
- **Log line và correlation ID liên quan:** (`evidence/13-incident-log.txt`) lọc `data/logs.jsonl` trong khoảng sự cố thấy 5 cặp `request_received`/`response_sent`, tất cả `feature=monitoring`, session `k4-l3a-challenge-s01..s05`, `latency_ms` 2652–3832. Log line chậm nhất: `response_sent` `correlation_id=req-0fa955c4`, session `k4-l3a-challenge-s04`, `latency_ms=3832`, `ttft_ms=50`, `tool_success=true`. Ngay trước đó có `incident_enabled` `{"name": "rag_slow"}` lúc 16:16:51.
- **Trace ID và span gây ảnh hưởng:** (`evidence/14-incident-trace.txt`) lọc metadata `correlation_id=req-0fa955c4` ra trace `4e7c4306a3982b88a65b01dd6534a0d7`:
  - `lab-agent-run` 3833 ms, trong đó span **`retrieval` 2502 ms**, `llm-generation` 157 ms.
  - Bốn trace còn lại giống hệt nhau: retrieval 2501–2502 ms trên tổng khoảng 2654 ms (94%), generation 152 ms.
  - So sánh: trace bình thường `e2c5a43a85cb0b316c2e8bba08a781db` (CP2) có retrieval **0 ms**, generation 151 ms.
  - Riêng `req-0fa955c4` dư thêm khoảng 1.17 s giữa lúc retrieval kết thúc và generation bắt đầu. Đó là lần fetch prompt đầu tiên từ Langfuse sau khi API khởi động lại lúc 15:24; khoảng này không có span riêng nên không thấy trên waterfall.
- **Root cause:** bước retrieval (vector store) bị chậm thêm cố định khoảng 2.5 s cho mọi query, do incident `rag_slow` được bật lúc 16:16:51. Bằng chứng từ ba nguồn cùng chỉ về đây:
  - Metric: latency tăng nhưng TTFT không đổi.
  - Log: mọi request challenge đều chậm, không có lỗi.
  - Trace: span `retrieval` tăng từ 0 lên 2502 ms, generation không đổi.

  Độ trễ gần như bằng nhau ở mọi query, nên nguyên nhân là dependency chậm chứ không phải một query cụ thể. LLM và prompt không phải nguyên nhân: cùng prompt v1/production, generation vẫn khoảng 152 ms.
- **Fix action:** khôi phục retrieval bằng `python scripts/inject_incident.py --disable` (tương đương failover sang vector store khỏe hoặc rollback thay đổi hạ tầng retrieval). Kiểm chứng (`evidence/15-incident-fix-verification.txt`): tắt `rag_slow` lúc 16:27:53 (+07), chạy lại `python scripts/load_test.py --challenge --concurrency 5` lúc 16:28:01. Cả 5 query challenge giờ có `latency_ms` 152–154 (trước fix 2652–3832), TTFT vẫn 50 ms. Trên trace, span `retrieval` còn 0–1 ms, ví dụ `req-a7c23e57` (cùng session s04 với request chậm nhất trước đó) có trace `e3f3bf10096fe1b1f4b9473bb6035fa4`, tổng 154 ms. Latency quay về đúng baseline chứng minh root cause nằm ở retrieval.
- **Preventive measure:**
  1. Đặt timeout cho retrieval (ví dụ 1 s), khi quá thì trả lời với fallback không có context và đánh dấu `tool_success=false`, để một dependency chậm không kéo cả request vượt SLO.
  2. Ghi thêm field `retrieval_ms` vào log `response_sent` để dashboard tự khoanh vùng span chậm mà không cần mở trace.
  3. Alert `latency_p95_degraded` (P95 > 2000 ms trong 5 phút) sẽ bắt được sự cố này nếu nó kéo dài. Challenge chỉ kéo dài khoảng 15 giây nên chưa đủ duration.
  4. Chạy agent đồng bộ trong threadpool (endpoint `def` hoặc `run_in_threadpool`) để một retrieval chậm không chặn event loop. Ở CP2 khi `rag_slow` bật với concurrency 5, client phải chờ 10–13 s dù server chỉ đo khoảng 2.65 s.

## 8. Giải thích và tự đánh giá

- **Một quyết định kỹ thuật quan trọng và lý do:** không ghi Langfuse `trace_id` vào structured log, chỉ dùng `correlation_id` làm khóa nối log với trace. `trace_id` là 32 ký tự hex; regex SĐT (`(?<!\d)0\d{9}(?!\d)`) chỉ chặn chữ số ở hai đầu, nên một chuỗi như `a0123456789b` trong trace ID sẽ bị scrub hỏng hoặc bị validator báo là PII. Tôi ước tính khoảng 7% cho mỗi lượt 10 request. `correlation_id` (`req-` + 8 hex) quá ngắn để khớp regex và đã có sẵn trong metadata trace.
- **Một lỗi/blocker đã gặp:**
  1. Truy vấn trace qua SDK `api.trace.list` trả HTTP 410 `LEGACY_API_UNAVAILABLE_FOR_NEW_ORGANIZATION`, vì org Langfuse tạo sau 16/09/2026.
  2. Sau khi promote label, request đầu tiên vẫn có thể dùng prompt cũ do SDK cache prompt 60 giây.
- **Cách tìm nguyên nhân và xử lý:**
  1. Đọc body lỗi 410; nó chỉ sang endpoint mới `GET /api/public/v2/observations` (kèm `fields=core,basic,usage,metadata,prompt,model`). Tôi đổi sang endpoint này để kiểm tra trace có đủ ba observation, prompt link, usage và cost.
  2. Với cache prompt: đọc `resolve_prompt` thấy `cache_ttl_seconds=60`. Khi thử promote/rollback, tôi gửi request qua một instance API mới khởi động để loại bỏ cache, và ghi rõ độ trễ tối đa 60 giây này trong runbook.
- **Cách hiểu luồng Metrics → Logs → Traces:** mỗi tầng trả lời một câu hỏi khác nhau, và tầng sau thu hẹp phạm vi của tầng trước.
  - **Metrics** trả lời *có vấn đề không, từ khi nào, nghiêm trọng đến đâu*. Ở challenge, panel latency cho P95 3832 ms so với 152 ms bình thường. Các panel khác cũng cho thông tin: TTFT không đổi và error 0%, tức hệ thống chậm chứ không lỗi, và chậm trước bước generation.
  - **Logs** trả lời *request nào bị ảnh hưởng*. Lọc `response_sent` trong khoảng 16:16:51–16:17:15 ra đúng 5 request, cùng `feature=monitoring`, kèm log `incident_enabled rag_slow` ngay trước. Log cho `correlation_id` cụ thể (`req-0fa955c4`).
  - **Traces** trả lời *chậm ở bước nào bên trong request*. Dùng cùng `correlation_id` mở trace `4e7c4306…` thấy span `retrieval` chiếm 2502 ms, generation 157 ms.
  - **Root cause** chỉ được kết luận khi cả ba tầng nhất quán, và được kiểm chứng bằng fix: tắt `rag_slow` thì latency về 152–154 ms và span retrieval về 0 ms.
  - Nếu thiếu `correlation_id` chung giữa log và trace thì chuỗi điều tra bị đứt ở bước 2→3. Đó là lý do CP1 phải làm correlation ID trước.
- **Vai trò của prompt version, token/cost, SLO hoặc rollback trong vận hành LLM:**
  - **Prompt version:** prompt là một phần của "code" nhưng thay đổi ngoài chu kỳ deploy. Mỗi trace ghi `prompt_name`/`prompt_version`/`prompt_label`, và generation link tới prompt, nên khi chất lượng hoặc cost thay đổi có thể biết request nào dùng version nào. Khi thử, v2 làm `tokens_in` tăng từ 32 lên 49 cho cùng input.
  - **Token/cost:** với LLM, cost tỉ lệ với token chứ không cố định theo request. Một prompt dài hơn hoặc câu trả lời dài hơn (như incident `cost_spike` nhân 4 output tokens) làm tăng chi phí mà không làm hệ thống lỗi, nên cần panel và alert riêng (`cost_burn_high`).
  - **SLO:** biến "nhanh" thành con số đo được (99.5% request ≤ 3000 ms trong 28 ngày). Error budget 0.5% cho biết còn được phép rủi ro bao nhiêu: còn budget thì có thể thử prompt mới, gần hết thì ưu tiên ổn định.
  - **Rollback:** app lấy prompt theo label chứ không theo version, nên rollback chỉ là chuyển label `production` về v1 (`prompt_labels.py promote 1`), không cần deploy code. Cần lưu ý độ trễ tối đa 60 s do cache.
- **Điều quan trọng nhất đã học:** con số đo ở server không nhất thiết là trải nghiệm của người dùng. Khi bật `rag_slow` với concurrency 5, `latency_ms` trong log chỉ khoảng 2.65 s (trong SLO) nhưng client chờ 10–13 s. `retrieve()` dùng `time.sleep` đồng bộ trong endpoint `async def`, làm event loop bị chặn và request xếp hàng, mà thời gian xếp hàng không nằm trong bất kỳ span hay log nào. Muốn SLO phản ánh đúng người dùng thì phải đo từ phía client hoặc ở tầng ngoài cùng, và phải hiểu mô hình concurrency của app.
- **Hạn chế hoặc phần chưa hoàn thành, nếu có:**
  - LLM và retrieval là mock (`FakeLLM`, `mock_rag`): câu trả lời cố định, quality score là heuristic, TTFT là giá trị giả lập 50 ms.
  - Preventive measure ở mục 7 (timeout retrieval, field `retrieval_ms`, chạy agent trong threadpool) mới là đề xuất, chưa triển khai, để không làm thay đổi hành vi của challenge.
  - Alert mới được định nghĩa trong `config/alert_rules.yaml` và `docs/alerts.md`, chưa nối vào hệ thống gửi Slack thật. Dashboard là HTML tĩnh sinh từ log (tự reload), không phải công cụ giám sát chạy liên tục.
  - `completion_start_time` hoạt động: UI Langfuse hiện `ttft 0.05s` trên generation (`evidence/08-trace-metadata.png`), nhưng trường `timeToFirstToken` trả về từ `GET /api/public/v2/observations` vẫn là `null`. Vì vậy muốn tính TTFT tự động thì phải đọc từ log hoặc dashboard.
  - SDK Langfuse tự ghi public key (`scope.attributes.public_key`) vào metadata của observation, nên trace hiển thị public key. Đây không phải secret key, nhưng tôi đã che dòng này trong ảnh `07` và `08`.
  - Panel tokens báo BREACH ở CP2 vì workload thử dày hơn giả định của contract. Tôi giữ nguyên threshold và giải thích thay vì sửa contract.
  - Lỗi đã sửa ở CP4: bản đầu của `build_dashboard.py` chia số request cho khoảng thời gian của *mọi* record, kể cả `app_started`. Vì vậy khung 16:19 báo traffic 0.1 req/phút, lệch với ảnh dashboard chụp lúc 16:25 (5.0 req/phút). Tôi đã sửa để chỉ tính theo event `request_received`, thêm test hồi quy, và tạo lại `evidence/12-incident-metric.txt`.

## 9. Checklist trước khi nộp

- [x] Kết quả và evidence thuộc commit SHA cuối.
- [x] Tất cả ảnh/output mở được bằng đường dẫn tương đối.
- [x] Incident evidence nối đúng metric → log → trace.
- [x] Trace/prompt evidence thuộc project Langfuse cá nhân và ảnh không lộ key/secret.
- [x] Repository chạy lại được theo README.
- [x] Không có secret, API key, PII thô hoặc evidence của người khác/lớp khác.
- [x] URL repo và commit SHA cuối đã được nộp trên LMS/Codelabs.
