# Parallel Worker readiness / recovery increment

基準：`ee33371e64aad186120578c8ce069ab67b844e8a`，分支 `feat/orchestrator-phase1-2`。
本輪授權僅涵蓋實作、零 Provider 故障注入、回歸與本地 checkpoint。
**本輪 source / offline / native zero-provider checks 已驗證；新真實雙 Worker Campaign NOT_RUN。**
歷史 `game-parallel-20261010-01` 保持 `BLOCKED_NO_RETRY`，不回填 PASS、不移轉未用 Review 額度。

## 原因與採用方式

既有 Runner、Queue、Supervisor、RepoAdapter、Validator、Review 與 Integration 繼續使用。
舊 v1 將 first ordinary failure 的 60 秒 deadline 保留到整個 turn 結束；即使修復成功，
後續 Test/Build 仍會耗掉此窗口。任何 attempt exception 也會觸發 shared stop。
readiness 原先沒有檢查 `rg`；歷史 owned-cgroup 採樣曾達 61/64 與 55/64 tasks。
本輪採 Extend / Compose，不增加依賴、外層 sandbox、Provider attestation 或新 Scheduler。

## Failure Policy Matrix

| 事件 | 新處理 | Scope / deadline |
|---|---|---|
| 已識別普通工具／測試錯誤 | 同 turn 自主修復，整個 attempt 最多 3 次失敗 | 累計 60 秒 repair；不重補次數／時間 |
| 同一 literal argv 成功重跑 | 關閉對應 unresolved 項目 | 保留原始事件、journal hash chain |
| 改用合法替代工具／修正參數 | 無關 exit 0 不足；最後修改／failure／非 check 之後全部 pinned checks 成功才確認修復 | 不安裝工具、不擴大 scope |
| pinned Test/Build | 必須有相符的 native started/completed item ID 與 exact argv，序列執行 | registry timeout 與 task 剩餘時間取小；執行期間暫停 repair 計時 |
| edits、prose、任意 echo 成功 | 不解除 repair；file change / 非 check 使 suite closure 失效 | 不授予 acceptance 權限 |
| turn.completed 仍 unresolved／check lifecycle 不明 | STOP | 全域、零 retry |
| repair count/time 耗盡、task/check timeout | 立即取消並 fencing | 全域；不把中止中的 Provider 當完成 |
| permission、sandbox、approval、config drift、lease/fencing、未知事件、Provider UNKNOWN | 立即 STOP | 全域；未知 cleanup 保留 locks/capacity |
| Controller validator 的已知普通 assertion failure | 僅在 Worker 完整完成、scope 未漂移、全部程序 clean、lease/pins 有效與 watchdog handoff 後，寫 FAILED | task-local；健康已派工 Worker 可收尾至 REVIEW |
| 取消／DB／journal／watchdog／程序清理失敗 | STOP，保留 UNKNOWN | 全域、零 retry |

v2 不變更最大失敗次數、60 秒修復額度或 600 秒 task ceiling。每個 task 的既有 budget
仍是總期限，包含 probe、Worker 與 Controller validation；單一 check 不能延長它。
較長 registry timeout 仍受既有 policy 上限 600 秒與 task 剩餘時間限制；本次遊戲 checks 為 120 秒。
v1 保留原 first-failure deadline 語義。歷史 journal 僅 readonly audit，不 resume 或轉換政策。

## Readiness、持久化與隔離

- `development_tool_probe.py` 是固定 native `command/exec` probe；使用 Worker 的 cwd、PATH、
  原生 profile 與 scope。檢查 bash、rg、grep、find、cat、Python、Node、Git 的 availability、
  resolved path 與 executable hash；必要工具缺失／schema、PATH、hash 不符即停止。
- per-attempt receipt 綁定 queue/task/attempt/epoch/policy/native config/probe；exclusive creation 拒絕 replay。
  Worker prompt 收到 inventory、合法 fallback guidance 與 receipt hash；這不是可新增權限的指令來源。
  `--prepare` 也探測；真正 dispatch 前再探測，避免只依賴舊 preflight。
- 所有 scope / artifact / scratch / required checks / Controller validation 規則保留。
  原生工具 inventory 是 Development 的 controller-observed evidence，**不是 live namespace attestation**。
- `isolated_task_failures` 持久化 task/attempt/epoch/receipt hash。未標記的歷史失敗、
  HELD/CANCELLED、receipt drift 仍為 global stop。task-local failure 不發布 artifact、不進入 PASSED。
- task-local failure 後不 refill、不追加 Review、不整合成功 subset。claim / dispatch 與 Review /
  Integration 預約容量的 transaction 都重查 failure latch。已在執行的健康 Worker 僅收尾；
  依賴失敗上游的任務保留 PENDING。重啟不能清除 latch、補額度或重試失敗 attempt。
- 保留 1 GiB / swap 0 / 64 cgroup tasks 上限。per-invocation `GOMAXPROCS=2` 與既有
  UV/Rayon thread caps、單 Vitest worker 限制一起使用；Global config、Repo capacity 與原生 permissions 不變。
  取樣保存 PID、memory、CPU 與 OOM/PID-limit events；缺資料保持 UNKNOWN。

## 實際驗證

離線 baseline：原有 241 orchestrator tests PASS；本輪增加 16 項 causal tests。
回歸命令（repo 根目錄，Inventory 除外）：

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -B -m unittest discover -s orchestrator_tests -v
python -B -m unittest test_response_diagnostics test_decision test_phase2a test_resources test_combined test_inventory_safety
# cwd: payload/jev
python -B -m unittest test_inventory
```

結果：**257 orchestrator + 77 Jev + 12 Inventory = 346 PASS，無 skipped。**
新增案例含精確修復、替代工具／完整 suite closure、修復累計額度、unresolved completion、
check/task timeout、v1 不變、native Runner seam ordinary-vs-denial/unknown、健康 sibling drain、
依賴不釋放、late-latch Review/Integration、replay/stale/tamper、restart 與 resource counters。
原有取消、watchdog、DB busy、fencing、程序殘留與 unknown capacity guards 仍通過。
測試使用固定事件／Runner seam，不冒稱真實模型執行。

另在新的隔離遊戲 clone/worktree 執行官方 CLI 0.161.0 的 **零 Provider** `command/exec`：

| 檢查 | 實際結果 |
|---|---|
| 工具 | `rg`、`python` MISSING；bash/grep/find/cat/python3/node/git AVAILABLE |
| 遊戲 Vitest | 35 files / 308 tests PASS |
| Typecheck | `tsc --noEmit` PASS |
| Build | Vite Build PASS，輸出僅 `.tmp/build` |
| cancel injection | CANCELLED；fence callback 先於 stop request；空 cgroup/readers closed |
| timeout injection，診斷 02 | TIMEOUT_OR_UNKNOWN；fence callback 先於 stop request；空 cgroup/readers closed |
| 程序 readback | 兩份診斷共 12 個 owned units 全部 inactive / MainPID=0 |
| Source/config | 診斷 02 前後一致；Queue 0 tasks / 0 dispatch；Review turns 0 |

診斷 01 的 timeout 注入 **FAIL 保留**：systemd 的 `RuntimeMaxSec=2s` 先終止程序，
Controller 舊 `seconds+5` deadline 只記成 EXITED/exit 1，未觀察到 fence callback。
修正為啟動前建立 `monotonic()+seconds` 的 Controller deadline，沒有增加 OS timeout 或資源上限。
新的診斷 02 觀察到約 2.047 秒停止完成，fence 先於 stop；不是所有排程情況下的硬即時保證。

診斷 02 資源採樣（cgroup tasks 包含 threads，不等於單純 process count）：

| Native command | tasks peak observed /64 | memory peak observed bytes | last sampled CPU usage us |
|---|---:|---:|---:|
| Vitest | 53 | 416907264 | 10612029 |
| Typecheck | 43 | 353574912 | 4408295 |
| Build | 59 | 170659840 | 659266 |

資料是採樣，不是完整生命週期 accounting；Build 僅觀察到 5 個 tasks 餘裕。
不能推論真實 Worker + Code Mode Host 一定有同樣餘裕，也不宣稱已消除所有資源風險。

ignored evidence：`runs/parallel-recovery-20261010-01/`，含原始診斷 01/02、64 檔 hash manifest、
回歸 logs、候選 source archive 與 review diff；raw configs / journals / queue 不提交。

- native evidence manifest SHA-256：`f912628d6bccee873670ab98365462a86087861744beb0932bd5d7645b0f83a7`
- report-02 SHA-256：`5b9ef05799a5dde9081e8b949cfb9e3edff01a60718f61cd16371e719f510e5b`
- Windows readback：64 檔 hash 全部一致。

獨立 architecture 與 security advisory reviewers 已覆核 source、causal tests 及 native report，
前次三項 findings 修復後均 accept；不是實際 Task Review，也不增加任何模型 Campaign 授權。

## 下一個有界 Campaign 提案（NOT_RUN）

需新的明確授權：2 Sol/medium Worker dispatch + 2 Astra/high Review，零 attempt retry；
新 Campaign/Task/Attempt/evidence，新測試 clone max_active=2 且不超 Global 上限，原遊戲 repo 保持 1。

1. 全新 readiness：工具 inventory、固定單 worker Vitest/Typecheck/Build、角色設定及原生安全政策。
   依資源採樣確認有餘裕；不得為通過而提高 1 GiB/64 tasks。
2. A 只擁有 `scripts/zip.mjs`、`tests/zip.test.ts`；B 只擁有 `scripts/package-itch.mjs`、
   `scripts/package-itch.d.mts`、`tests/package-itch.test.ts`。B 的獨立任務只驗 baseline 合法 ZIP 相容性，
   不要求未交付的 A 新語義；跨功能危險 entry 驗證留給 integration。若實際出現依賴，先重拆 DAG。
3. 移除舊 task goal 中 first-failure 60 秒描述，採 v2。固定 checks 序列執行，保存真實 lifecycle；
   optional missing tools 只用盤點中 AVAILABLE 的合法替代方式，不安裝套件。
4. 兩 Worker 都成功才消耗獨立 Review；兩項 PASSED 才執行隔離 integration union oracles /
   Build/Test / artifact / restart 核對。任何任務失敗則整體不 PASS。
5. 觀測真實程序重疊、native failure events、repair closure、cgroup headroom、tokens 與耗時。
   UNKNOWN/安全/lease/取消/超額立即全域停止；只有已知且完整收尾的 ordinary validation failure
   可以讓健康已派工 sibling 收尾。沒有額外 retry、Review、merge、push 或 Phase 3。

尚未驗證：新版真實同 turn recovery、雙 Worker 故障隔離、真實 Review/Integration 成功。
整體 Agent Factory 保持 **PARTIAL**；本輪不申請 5 Workers，也不啟動背景 Campaign。
