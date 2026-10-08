# Development Execution Mode

2026-10-08 使用者調整 Agent Factory 優先方向。日常開發明確信任 Codex
官方原生 Sandbox、Approval 與模型安全機制；額外的同次 namespace 證明與
provider 模型 attestation 不再是 Development 的前置條件。

這個決定只授權新 Development Queue，不降低舊 Production Queue 的 gate。
本候選沒有安裝或修改 Global runtime。M3 真實 Repo 與後續容量擴充尚需獨立驗收。

## 責任與配置

沿用 Task DAG、SQLite Queue、Lease/Fencing、Rule Router、Worktree Allocator、
ArtifactStore、Dependency Snapshot、Supervisor 與 Merge Queue。沒有重寫控制面。

| 配置來源 | Development 行為 | 保留的底線 |
|---|---|---|
| Controller constructor | `evidence_mode='DEVELOPMENT'` → compiled execution mode `development` | 新 policy hash 與 durable queue binding；拒絕改開舊 queue |
| Global controller defaults | 角色與 Scheduler 預設 | active≤2、required/independent review、Astra/high、merge disabled |
| Repo `.codex/orchestrator.json` | capabilities、literal tests、allowed files、較嚴 budget | 自訂 controller namespace，非 Codex 原生配置 |
| Workspace/session | 合法 model/effort、Jev on/off、routing | 不能選 mode、降 review、擴 Repo scope 或換 pinned validator |
| Codex native profile | 沿用已準備 runtime 的 `worker-minimal`、`never`、`auto_review` | minimal read、artifact directory ceiling、Git/指引 read、network disabled；Global 不動 |

本固定 WSL fixture runner 只支援既有 runtime pins 與 artifact 目錄 ceiling。
一般 Repo/Windows adapters 尚未宣稱可用。Runtime pin 或 policy 變更會拒絕執行。

0.161.0 在這個 named profile 對檔案型 writable root 的 native instruction loader
會將 `.git/.aws` 附加在檔案名稱之下而失敗。Worker 因此沿用原 profile 的
`artifact/` 目錄寫入範圍。**精確 allowed_files 是 Controller 的結果驗收；
不是 OS 阻止該目錄內所有暫時越界寫入的證明。** Validator/Reviewer 的
artifact 目錄則只讀。任何接受產物的 final diff 必須完全符合 allowed_files。

## 日常驗收鏈

```text
New Task → Queue claim/lease → durable dispatch intent
→ official codex exec (Sol/medium, native sandbox)
→ real completion + completed tool item + actual diff
→ artifact guard + pinned registry plan
→ official app-server command/exec (readonly native validator)
→ artifact SHA/custody + durable receipt → REVIEW
→ separately launched Astra/high CLI reviewer
→ typed completion + challenge/attempt/artifact/owner checks → PASSED
→ Merge Queue HELD: human authorization required
```

CLI exit 0、caller model name 或 caller review JSON 不能單獨取得 PASS。
Validator 沒有 direct-host fallback；固定 fixture 額外採純函式 AST guard 與
精確完成標記，避免 import-time exit 繞過測試。Worker/Validator/Reviewer 全部
結束並確認 cgroup cleanup 後才能接納結果。cgroup 是 lifecycle 控制，不冒稱 sandbox。

Review 前後都核對 published artifact hashes。Reviewer 使用獨立 ephemeral CLI
session，artifact readonly，Controller 在真實 completion 後寫入 receipt。
Review nonce 不可重用；review dispatch 在重啟後不可自動重發。Review 占 durable
capacity slot；Supervisor 在 review 期間持續更新 owner lease，失主/timeout 即取消。
未知清理狀態保留 slot，不能自行釋放容量。

Assurance level 為 `CONTROLLER_EXECUTION_NATIVE_TRUST`：可信 Controller 啟動參數、
config/read、執行 events 與產物綁定。官方 exec events 不提供 provider 模型身分
證明，因此 `provider_attested_model=None`；不把 configured Astra/high 偽稱 attestation。

## 保留但停止的 High-Assurance 模組

| 既有模組/入口 | Development 預設 | 保留狀態 |
|---|---|---|
| `tools/external_executor_poc.py` | 不啟用，不被 runner 匯入 | 原 NO-GO、raw evidence 與 gate 不變 |
| `tools/linux_mount_diagnostics.py`、`orchestrator/admission.py` containment attestation | 不作 daily gate | Standalone VERIFIED 與 Live UNKNOWN 的範圍不变 |
| Production `Phase2Queue._import_review` provenance gate | 不作 Development importer | 仍 BLOCKED；未移除、繞過或重新解釋 |
| Production `ValidatorRegistry.run` admission | 不以 Development 放寬該方法 | 仍禁止未 sandbox 的 Host 執行 |

沿用現有獨立 source 與 entrypoints 保存研究結果，沒有另建 wrapper 框架。
日常 Development 不載入它們。它們目前停止且 BLOCKED，不提供已驗收的 backend
切換；任何未來重啟都需要新的明確任務與驗收，不是 Workspace 的靜默覆寫。

## 受控命令與里程碑

`tools/development_smoke.py --runtime <prepared-runtime> --run-root <fresh-child>`
先執行官方 config/read、thread/start 與 readiness command；不發 `turn/start`。
CLI startup 可能有 provider metadata HTTP，零 inference 不等於完全無網路。

明確取得新 inference envelope 後加入 `--execute`：最多三個 Worker turns
與三個獨立 Reviewer turns，各 task 一次 attempt，無自動重試。
單 Worker PASSED 後才釋放兩個平行 dependent tasks。新 Task IDs 綁新 queue。
可用 `--predecessor-run <retained-run>` 記錄前次 hash/attempt/count；不重開或改寫舊 queue。

M1/M2 的實際狀態、run ID、hash 與測試結果記錄在 Phase 1–2 ADR；
未通過的步驟保持 BLOCKED/NOT_RUN，不使用離線 stub 補作 runtime PASS。

最新 Campaign `development-campaign-20261008-96f3c4f5` 已取得三個真實 Task
的修改、Controller Validation、獨立 Review 與 PASSED，並重核相依快照與 restart custody。
Campaign 整體仍為 **PARTIAL**：乘法 Worker 有一筆 `python` exit 127，
同 turn 改用 `python3` 後成功；較廣的「任何 FAIL 立即停止」沒有達成。
目前 Supervisor 停損控制 attempt/validation/review，不能宣稱逐項工具即時取消。
3 Worker＋3 Task Review 額度已用完，不重試；raw FAIL 與 Controller PASSED 均保留。
完整證據、預算、限制與下一輪停止政策要求見
[Phase 1–2 ADR](orchestrator-phase1-2.md) 的新 Campaign 記錄。

## Worker Failure Policy v1（新的 Development Attempts）

2026-10-08 在 `6c52ca6` 後增量實作。只對新的 attempts 使用，不重新解釋
上述 Campaign PARTIAL，也不重開歷史 queue 或補發 dispatch intent。
沿用 `NativeDevelopmentRunner`、`run_cgroup`、SQLite lease/fencing 與既有 Supervisor。
政策來源是受信任 Controller source，並納入 compiled policy hash；task 或 Worker
不能自行宣告某個錯誤可恢復。

| Failure | 判定來源 | 同 turn 修正 | Controller 動作 |
|---|---|---|---|
| 普通工具／測試錯誤 | CLI `command_execution/failed`、exit 1/2/127，加固定普通診斷訊號 | 允許，受下述上限限制 | 保存 raw event、hash chain、失敗次數及固定 deadline |
| 權限／Sandbox／Approval 拒絕、唯讀路徑、取消、timeout、lease／fencing 訊號 | 可信 CLI envelope 與 Controller watchdog；拒絕訊號優先 | 不允許 | latch STOP、durable fence、取消共享執行、停止 owned cgroup |
| lease 失效、Controller/policy/config 漂移、watchdog 或 evidence 寫入失敗 | Controller 的 Queue、compiled source、runtime config 及 callback | 不允許 | STOP；無法證明控制／清理完整時 HELD，保留 locks/slot |
| Provider UNKNOWN、turn failed、缺 completion、格式不明、未知工具、replay | 增量 CLI JSONL parser／EOF | 不允許 | fail-closed；新 dispatch retry 為 0 |
| 超出次數／恢復時間／task runtime／output cap | Controller 的 monotonic clock 與計數器 | 不允許 | STOP；不可透過成功事件或重啟重置 |
| 取消指令非零、callback UNKNOWN、殘留程序或未關閉 output readers | 實際 systemd/cgroup lifecycle receipt | 不允許 | `CONTROL_UNKNOWN`／`CLEANUP_UNVERIFIED`，不得接納產物或釋放未知容量 |
| Validator、artifact、必要 Review 失敗 | 既有 Controller acceptance/review chain | 不適用此 Worker 修正額度 | 保留既有 STOP／NO_RETRY／Review Gate |

固定普通診斷清單包含 `command not found`、常見 Python/JavaScript exception、
unittest/pytest failure 及 TS/CS compiler error。exit code 本身不授予修正資格。
未識別的 build/tool 錯誤停止；stdout 包含拒絕訊號即使 exit 0 也保守停止。
清單不是對任意工具輸出的完備語意分類，可能發生保守誤停。

**預算：最多 3 筆不同 completed tool 的可恢復失敗；第 4 筆立即停止。**
首次失敗後同一 turn 必須在 60 秒內完成，亦受較短的 task runtime 限制。
成功工具不重置計數或時間，沒有新的 attempt、模型 turn 或 dispatch retry。
可信 Controller 可收緊此政策；不可透過 task input 擴大上限。

stdout 使用 `read1()` 增量讀取並保存原始 JSONL；逐筆檢查 deadline，fatal 不會
被稍後 completion 清除。guard 每 0.2 秒檢查 claim/config，heartbeat 仍每 2 秒更新。
持久化及 stop callback 失敗的 `control_unknown` 會傳至 lifecycle receipt 與最終
cleanup 判定，不因 DB 後來恢復而變成已驗證。成功發布前停止並 join watchdog，
再檢查 VALIDATING、runtime pins/config，避免正常 REVIEW 被當成 lease 失效。

fatal 先送 local/shared 取消訊號，再嘗試持久 fence。watchdog 的 claim/heartbeat
查詢與停止路徑的 fence/event 寫入，各採 50ms SQLite busy wait；一般 Queue 的
10 秒預設不變。DB 持續不可用時不能宣稱即時寫成 HELD；保留控制 UNKNOWN、
既有 task/locks/slot，待 DB 恢復才核實 ledger。50ms 是單次 DB 等待，非總停止 SLA。

每次 attempt 有獨立 `failure-policy/policy.json`、逐筆 hash-chain records、raw events、
execution/failure receipt。重啟只讀核對，不重新建立 monitor 或補回執行額度。
這些是 Controller 保管的證據，不是 provider 簽章。

### 本輪零 Provider 驗證與限制

`tools/worker_failure_probe.py` 使用固定 Python event emitter、既有 Native runner 的
控制 callback/watchdog 與真實 systemd cgroup；**沒有啟動 Codex CLI、模型或 Jev**。
scope 是 `SYNTHETIC_EVENT_CONTROLLER_AND_CGROUP_ONLY`，不宣稱 native sandbox 等價。

最終 run `worker-failure-policy-final-20261008-aa10fc53`：14 案例全部符合預期；
284 項完整 regression 通過，fresh Controller audit 與 155 檔 custody 核對通過。
實際結果與完整命令見 ADR，公開 logs/evidence 留在 ignored `runs/`，不提交 runtime journal。

停止是**觀測事件後的取消**，不是 atomic pre-tool gate；不能保證 CLI 在 Controller
看見 fatal 前沒有開始下一個工具。固定 emitter 的觀測／清理延遲不是普遍 SLA。
restart case 是執行期間重開 Controller 並注入 lease expiry；強制殺死 Controller 的
hard crash recovery 未測。kernel `RuntimeMaxSec` 保留，但不冒稱 crash 時即時停止。
新 failure policy 在真實模型上的驗收本輪 NOT_RUN，需要新的有界授權。

### 2026-10-09 opt-in real-repo adapter

`NativeDevelopmentRunner(..., repo_adapter=RepoAdapter(root))` 擴充 existing native path，
沒有改 synthetic 預設。Adapter 的 source/base、dependency/Node/config pins、scan/mode
policy 及 persistent readiness binding 都在 controller custody，task input 不提供 commands。
實際遊戲 baseline native 308 tests/build PASS；單一 real dispatch 被 startup error item
即時取消，沒有修改或 Review/PASSED。結果及狀態見 [report](game-repo-development.md)。
Development per-invocation warning suppression 的 source/offline check PASS，runtime NOT_RUN。
歷史 FAIL/UNKNOWN 保留，未知 error 不放行，原生安全機制不關閉，無新派工或額度回補。
