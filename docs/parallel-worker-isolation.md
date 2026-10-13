# Parallel Worker 自主修復與分支故障隔離

日期：2026-10-10。基準 `8e683285d7ddb2189c53d85593668dc4ecd5a781`。
本輪依使用者要求，只實作、零 Provider 故障注入、回歸與本地 checkpoint。
沒有新真實 Campaign、Worker／Review dispatch、Jev 或 Global 設定變更。

## 實作與啟用範圍

Extend 既有 `worker_failures.py`、`development.py`、`phase2.py`、`supervisor.py` 與
`repo_parallel_campaign.py`。不替換 Scheduler、Queue、Worktree、Validators 或 Review Gate。

新 Development Queue 可明確選擇 `failure_isolation='independent_tasks_v1'`。
Parallel Campaign 入口只在新 Controller 的 `controller/failure-isolation.json` 存在且精確為
以下專案自有契約時選擇新版；這不是 Codex 官方配置，也不授權任何模型請求：

```json
{"mode":"independent_tasks_v1","version":1}
```

未指定仍用 `legacy_campaign`。SQLite 持久保存模式 hash，重開時須相符；已有任務的
無 binding Queue 不得轉為新版，舊 latch 不重新解釋。Readiness、dispatch、Task Context 與
失敗 receipt 綁定此 hash。歷史 Campaign 01／02 的 FAIL、額度、source 和 evidence 不變。

## Failure Policy Matrix

| 情況 | 本輪處理 | 範圍／限制 |
|---|---|---|
| 可信 Repo 缺少 leaf，符合下方全部 ENOENT 條件 | `REPO_READ_ENOENT / RECOVER` | 同 turn；原 3 failed events、60 累計修復秒，不補額度 |
| 已知 command-not-found、語法／型別／測試 assertion | 原普通錯誤修復 | 原生事件、既有 count/time/task budgets |
| 精確失敗指令成功，或最後修改／失敗／非 check 指令後完整 pinned suite 成功 | 修復閉合 | 不以文字、edit 或任意 exit 0 解除失敗 |
| 已完成 turn 仍有未修復普通錯誤、必要 Worker check 缺失、無修改／缺 Artifact | `WORKER_ACCEPTANCE_FAILURE` | 確認完整 completion、process cleanup、scope、HEAD、inputs、lease 後只失敗本 Task |
| Controller 已知 validator assertion | `VALIDATOR_ASSERTION` | 可信 pinned validator、已知退出／清理與 custody；只失敗本 Task |
| 完整、獨立且合法的 typed Review REJECT | `REVIEW_REJECTED` | 持久 FAILED；不釋放依賴，不重派本 Task／Review |
| 權限／安全拒絕、未知工具或 protocol、Provider UNKNOWN | 全域停止 | 即時 cancel／fence，維持原 no-retry |
| 修復預算耗盡、task/check timeout、lease/fencing、取消／清理失敗、配置漂移 | 全域停止 | 中止 live turn 不能假稱 Provider completion 已知 |
| 未知 Review／artifact drift，或 Review dispatch 後 crash | 持久全域停止 | global latch；即使未寫完 failure receipt，未完成 Review intent 仍阻止 restart dispatch |
| 容量／可信資源配額暫時不足 | 既有 backpressure | 不提高限制；未知程序保留容量 |

ENOENT 首版刻意只支援：**已釘選 `cat` 絕對 executable + 單一 canonical 絕對 Repo 路徑 +
可信清單中已存在的公開 parent + host 確認 missing leaf + 整份輸出精確符合該 leaf 的 ENOENT**。
拒絕 shell 表達式、redirect、flags、reparse、外部／受保護路徑、額外 EIO／未知診斷與資料。
相對路徑、bare `cat`、多 operands、缺失 parent 不在此 recoverable 集合。
CLI command event 未提供經驗證的每次 tool cwd，不能把 turn 起始 cwd 或 caller 自報 cwd 當成證明。
故歷史 `cat tests/unity-preflight.test.ts vite.config.ts` 仍為 UNKNOWN，不回改裁決。

Controller 建立不可覆寫 `task-context.json`：排序後實際公開檔案／hash、workspace、baseline、
新建空 placeholder、tool readiness、必要 Test／Typecheck／Build 的 literal argv、attempt／epoch／policy。
排除 metadata、dependencies、scratch、受保護檔名；超過 2048 檔或 128 KiB 直接拒絕，不冒稱截斷後完整。
資料內容不放進清單。清單與 guidance 不授予讀寫權；原生 Sandbox 和 allowed-files 不變。
v3 failure journal 在 dispatch 前一次綁定 context，重啟只 audit，不重建執行或修復額度。

## 故障隔離與 Review

新模式下，普通失敗必須有 Controller 產生的正面 completion／cleanup／binding evidence，
才會存為 isolated FAILED，釋放本 Task 的 locks。未驗收上游的依賴保持 PENDING。
健康已派工與已入 Queue 的獨立任務可依原始 dispatch／Review／capacity budgets 繼續。
Review 仍序列執行且計入同一容量；dispatch 及 publication 在交易內再次檢查 global stop。
合法 Review PASS 才能產生 PASSED、釋放自己的下游。失敗 Task 不發布 accepted Artifact。

未知 Review 結果寫入既有全域 latch；無對應 `review_runtime` 的 durable intent 也會阻止新工作。
當次 publication 只豁免自身 matching nonce，仍驗 owner／challenge／epoch／artifact／independence。
任一任務失敗，整個 Campaign 不能 PASS，也不能對成功 subset 執行整合。
人工 Merge 授權、原生安全機制、active children 和原 Repo `max_active=1` 均保留。

## 驗證與證據

實際命令（PowerShell 設 `PYTHONDONTWRITEBYTECODE=1`）：

```powershell
python -B -m unittest discover -s orchestrator_tests -p test_enoent_isolation.py -v
python -B -m unittest discover -s orchestrator_tests -v
python -B -m unittest test_response_diagnostics test_decision test_phase2a test_resources test_combined test_inventory_safety
# cwd: payload/jev
python -B -m unittest test_inventory
```

新增 24 項 causal tests PASS。最終 **281 Orchestrator（65.948s）+ 77 Jev（2.860s）+
12 Inventory（0.021s）= 370 PASS，無 skipped**；原有 257 項 Orchestrator 全部保留。
測試包含窄 ENOENT／cwd／EIO／工具 hash／敏感路徑拒絕、同 turn suite 閉合、預算不補、
普通 complete rejection、安全 diff 優先、A 失敗 B 健康繼續及 C 獨立派工／Review、失敗依賴不釋放、
Review PASS 後健康依賴 READY、typed REJECT、late global、artifact drift、未知 Review／crash 重啟停止、
mode drift、stale／replay、全域 cancel／fencing、舊語義不變。
這些使用固定 CLI envelopes、真實暫存檔案／SQLite 與 Runner seam，**不是 native model 執行證明**。
既有 watchdog、程序樹清理、殘留／timeout、DB busy 與 restart guards 由完整回歸覆蓋。

Ignored evidence：`runs/parallel-isolation-20261010-01/`。保留 baseline、focused／final logs、固定 diff、
source/test hashes、獨立 advisory review 結果與回讀 manifest；不提交 raw journals／fixtures／live config。
最終 17 個 evidence 檔 hash 回讀一致；`evidence-manifest-final.json` SHA-256：
`e9635cfd7f3ef7dd1a497752e92f1a1b77dbef7a9992ebd0dd30242da54e77c0`。
最初 focused failure 是 state-only review seam 沒有正式 review envelope，因此先被 reviewed_batch 拒絕；
將 integration failure latch 提前檢查後修正。其工具輸出摘錄另存，不算真實產品／模型失敗。
獨立 architecture／security reviewers 找出 cwd／mixed EIO 及 Review restart stop 缺口；修復後均 accept，
只表示 source advisory review，不冒稱正式 Task Review 或額外 inference 授權。

## 下一次雙 Worker 實戰提案 — NOT_RUN

需新獨立授權：**2 Sol/medium Worker + 2 Astra/high Review，零 attempt retry**。
新測試 clone／Campaign／Task／Attempt／evidence；只 clone `max_active=2` 且不超 Global，原 Repo 保持 1。

1. 用本 checkpoint 凍結 Controller，明確 opt-in 新隔離模式；重新做工具與 pinned game checks readiness。
2. A：ZIP entry 安全強化，僅 `scripts/zip.mjs`／`tests/zip.test.ts`。
   B：獨立的合法 ZIP 打包入口相容性，僅 `scripts/package-itch.mjs`／`.d.mts`／相關 test。
   先核對真實檔案清單；B 不依賴尚未交付的 A 新語義，跨功能斷言留整合，否則重拆 DAG。
3. Task Context 提供正確路徑、pinned executable／argv、check/task budgets；Agent 在原 turn 內有限自我修復。
4. 普通且已知完成的任務失敗只阻擋自己與依賴；健康 Task 可消耗原分配 Review 額度。
   UNKNOWN／權限／控制／共享資源失效立即全域停止，不為取得證據故意消耗額外失敗 turn。
5. 兩項均 PASSED 才做隔離 Integration 的 union oracles／Test／Typecheck／Build／Artifact／restart 核對。
   保存真實程序重疊、修復 closure、tokens（缺值 UNKNOWN）、耗時及既有 cgroup headroom，不提高資源。

本輪功能與離線驗證可完成；真實新版 autonomous recovery／healthy branch delivery、完整遊戲雙 Worker
交付仍 **NOT_RUN**，Agent Factory 整體 **PARTIAL**。未排程背景 Campaign；沒有待自動重試的工作。
