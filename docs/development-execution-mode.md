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
