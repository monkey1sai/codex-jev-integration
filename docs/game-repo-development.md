# Real-game Development Adapter: local result

更新：2026-10-09，Asia/Taipei。Controller baseline `c328366d2c8b0ecfba7c2394ee1ca7dda12c708f`。

## Decision

**PARTIAL / real-game task BLOCKED**。最小 Repo Adapter、native game baseline、300 項
離線 regression 已完成；本次唯一 Worker 因 CLI startup error item 即時停止。
沒有遊戲程式修改、accepted artifact、Task Review 或 PASSED。不得重派或改寫歷史裁決。

來源 `monkey1sai/changshan-longdan` main `805db86f67ab2be152dea8abe57ca47f4e735fb7`。
原 `.claude/`、`.worktrees/` 未追蹤內容未複製/修改。以本地 bundle SHA-256
`cb4c1ecbb3626c46a4c9f81f7d97b8a970462a73dd7d67053f7781e70b793602` 建立獨立
Linux `source-repo` clone/detached worktree；無 remote fetch/push/merge。

實際價值任務：發布用 `scripts/zip.mjs` 未拒絕 `../escape.txt`、`assets/../x`、空名稱、
`C:/escape.txt`，本輪已重現。Worker scope 僅該檔及 `tests/zip.test.ts`。
外部 Controller acceptance 另測 dot/empty segments、backslash/drive/NUL、ill-formed
Unicode、duplicate encoded names、超长與恰好 65,535 UTF-8 bytes；保留 CRC/roundtrip/
deterministic bytes/合法 Unicode/空 archive。不增加 casefold/NFC/device-name 政策。
**本輪沒有修正此遊戲缺陷。**

獨立 scope review 同意 packaging-only 不改 gameplay、rendering、資產、Unity E-step；
S01–S08/render/play **NOT_APPLICABLE**，不是視覺 PASS 或 E-step DONE。
local Task Review 不等於 GitHub counted approval；本輪禁止 PR/merge。

## Reuse and boundaries

沿用 `NativeDevelopmentRunner`、Queue/Supervisor、allocator、Failure Monitor、ValidatorRegistry、
ArtifactStore、獨立 readonly Review 與人工 Merge gate。`RepoAdapter` 只組合來源身分、
native scope、dependencies、完整 scan/modes、trusted pins、review diff，不另建 executor。

- Global/native runtime 不改；Worker Sol/medium、Reviewer Astra/high、network off、
  approval never（deny-only）、auto_review、protected Git/instructions 保留。
- Repo 配置不改。Explicit controller session 新增 game_packaging，rules_only/Jev off、
  max_active=1、max_dispatches=1、max_attempts=1；既有 repo validators 不覆寫。
- 新 registry 是 literal argv、Node/acceptance hashes、package/lock/config pins、完整 copied
  dependency manifest。Linux Node 22.22.0 核對官方 checksum；Worker 外執行 lockfile
  `npm ci --ignore-scripts --no-audit --no-fund`，沒有 Global package 安裝。
- Native write roots 是 scripts/tests **目錄**；精確兩檔由 Controller diff gate 驗收，
  不宣稱 OS 逐檔隔離。Validator/Reviewer repo 唯讀，固定 `.tmp` scratch 可寫。
  node_modules 唯讀，build 到 `.tmp/build`，沒有 Host execution fallback。
- synthetic scan 保持 2 MiB/256；Adapter streaming scan 上限 256 MiB/20,000 files。
  不排除依賴/未追蹤檔，拒絕 reparse/special files；scratch 同樣查上限並分開核對。
  baseline mode/removal drift 拒絕；accepted ArtifactStore 的 2 MiB 上限不變。
- Adapter hash 持久綁 SQLite；execute marker/enqueue 前核對 readiness/envelope/campaign/
  adapter/policy/runtime hashes，舊 READY 不放行新依賴/config，exclusive marker 防 replay。

## Zero-provider evidence

01–04 preparation 原失敗保留：01 readonly pin 誤用 write parser；02 native nested merge
保留 artifact:write；03 default Vitest forks 觸及資源限制；04 single forks 在 ZIP test
SIGABRT。04 另用官方 single threads pool 的固定 probe 全套通過，原 04 仍 BLOCKED。
forks SIGABRT 底層根因 UNKNOWN，未放寬 sandbox/資源。這些前置工作沒有 Worker dispatch。

最終 frozen source-v6 / `game-campaign-20261009-05` 是 **READY_ZERO_PROVIDER**：
native startup、35/35 files、308/308 tests、tsc/Vite build（62 modules）、scope、
positive process cleanup、persistent bindings 全通過。CLI 0.161.0、bwrap、Code Mode
Host 使用既有固定 SHA-256；未用 cgroup 代替 Sandbox。

Registry 的有效 argv（node 絕對路徑固定）：

```text
node --v8-pool-size=2 node_modules/vitest/vitest.mjs run --configLoader native --maxWorkers 1 --no-file-parallelism --pool threads
node --v8-pool-size=2 node_modules/typescript/bin/tsc
node --v8-pool-size=2 node_modules/vite/bin/vite.js build --configLoader native --outDir .tmp/build
```

UV_THREADPOOL_SIZE=2、RAYON_NUM_THREADS=2；memory 1 GiB、swap 0、pids.max 64 保持。
未設 isolate:false。Pinned Node spawnSync sequence 任一步非零停止，無 shell interpolation。
`tools/game_repo_campaign.py --prepare ...` 無 inference；`--execute ...` 要求新且明確
授權的模型預算。**禁止再次 execute 本次 05**。Runtime/prep/bundle/run-root 明確傳入。

## Real dispatch and restart

Campaign `game-campaign-20261009-05`；Task `game-zip-d7fd789bb75f`；Attempt
`b620f13ed5054ca8bd5ed2d210ec6216`；native thread `01a11da1-3886-7b70-b7a1-3c7661f45b3e`。

Raw events：thread.started → item.completed(type=error, unstable-feature warning) →
turn.started。警告為 `Under-development features enabled: skip_host_skill_discovery...`，
全文保留 worker.jsonl。沒有 completed tool/provider completion；不能稱零 Provider 或
回補 dispatch。Monitor 按 `UNEXPECTED_TOOL → STOP`，task CANCELLED，worker CANCELLED。
Worker **1/1 consumed**，Review **0/1 NOT_RUN**，no attempt retry，artifact unpublished，
project diff 空，provider completion UNKNOWN。

Fresh Controller audit：failure hash-chain 通過；fence callback 在 terminate request 前，
remaining PIDs 空、readers closed、control_unknown=false、cleanup_known=true。
本次 stop request→execution ended **0.029845s**，僅一筆觀測，非 SLA/atomic pre-tool gate。
Public raw/intent/receipt、readonly SQLite backup、frozen source-v6、兩個未修改檔案、
restart audit 留在 ignored `runs/game-campaign-20261009-05/`，另保存整份 custody hashes。
不包含 auth contents，不隨 source commit 分享，不是 provider attestation。

## Safe correction and final checks

Development 單次 invocation 加 `-c suppress_unstable_features_warning=true`，不改 feature、
Global/runtime-home、sandbox/approval 或 error 分類。unknown/unexpected/error 仍 STOP。
Offline settings/negative error regression 通過；**修正的 native Worker效果 NOT_RUN**。
原 source-v6 FAIL 與 policy hashes 不改成修正後版本。

| Suite | Actual final result |
|---|---|
| `python -B -m unittest discover -s orchestrator_tests -v` | 211 PASS, 49.672s |
| `python -B -m unittest test_response_diagnostics test_decision test_phase2a test_resources test_combined test_inventory_safety` | 77 PASS, 3.960s |
| cwd payload/jev: `python -B -m unittest test_inventory` | 12 PASS, 0.020s |
| Total | **300 PASS**: prior 284 + 15 Adapter + 1 banner test, no skipped |

DONE（有限範圍）：Adapter、zero-provider game baseline、fatal lifecycle evidence、regression、
local source checkpoint。BLOCKED：real-game修改/Validation/Artifact/Review/PASSED。
NOT_RUN：真實普通錯誤 same-turn recovery、修正後新 Worker、雙 Worker、Jev/remote。
歷史 Campaign PARTIAL 不變；High-Assurance Production Admission 仍 BLOCKED/optional。

下一步只需新授權 **1 Worker + 1 Review / zero retry**，以修正後 source 建新 Task/Attempt，
重做 readiness，不能 resume/reissue 05。單 Worker 完整 PASSED 之前不擴大。

後續雙任務提案：A ZIP hardening；B 真實 dist/package 相容性驗證，接 A reviewed artifacts。
先處理已存在 source file 的 dependency snapshot composition，不允許任意覆寫 base。
只在隔離 integration 候選驗證，Merge 仍人工。Repo max_active=1 可依序執行兩任務，
並行需另核對合法容量。這是未執行提案，不宣稱 modified upstream source 交付已驗收。
