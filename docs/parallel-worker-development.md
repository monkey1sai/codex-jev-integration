# Parallel Worker Development — controller increment

基準：`feat/orchestrator-phase1-2 @54677b626dc5980c6f7938785c9f8cbe22de2951`。
本輪依使用者要求整理完成條件；不將此文件當成 Codex 原生配置或執行授權。

## 裁決與範圍

**PARTIAL**。控制面支援並行調度、多任務 Repo 接入與 reviewed integration；本輪沒有
新 Provider、Jev、Worker turn 或 Reviewer turn。真實遊戲雙 Worker、Build/Test/Review、
整合與 native overlap 都是 **NOT_RUN**。歷史 Campaign 05、06 及先前 PARTIAL/FAIL 不變。

保留原生 Sandbox、auto-review、Worktree、lease/fencing、Failure Policy、獨立 Review、
人工 Merge 及 Global production。沒有 push、PR、merge 或擴容。

## Adopt / Extend

- 沿用 `Phase2Queue` 的 SQLite transaction、dependencies、dispatch intent、locks、budget。
  v2/v3 contracts 增加可選 `priority: 0..100`，預設 0；排序只影響合法 READY candidates，
  同優先級仍 FIFO。不能繞過 scope、依賴、capability、未知結果、review 或容量。
- 沿用 `Supervisor` 的 ThreadPoolExecutor，沒有另建 Scheduler。其 metrics 是
  controller elapsed time／inflight submissions，**不是** native process overlap。
- capability 可選 `resources: {name: units}`；scheduler 可選 `resource_limits`。
  配額在 claim transaction 原子核對，HELD 與 native review slots 持續占用。
  這是可信配置的邏輯資源預留，不是 CPU benchmark 或新 OS 隔離。實際 native cgroup
  仍是每個程序鏈 MemoryMax=1 GiB、swap=0、TasksMax=64；cgroup 不取代原生 Sandbox。
- 增加 casefold file ancestor/descendant conflict；沿用既有 resource_locks。
- `dispatch_decision` 保存 policy hash、候選優先級、拒絕原因、資源用量及選中 task。
  相同 polling decision 去重，restart 不回補已消耗額度。

## Configuration matrix

| 項目 | 現況／規則 | 本輪動作 |
|---|---|---|
| Source Global defaults | max_active=2；不是已安裝 production 的證明 | 保留 |
| changshan-longdan | max_active=1 | 未修改 |
| Session scheduler | 可縮減 explicit Repo ceiling，不能提高 | 新增拒絕 gate |
| Models/effort | Sol/medium Worker、Astra/high Reviewer，或合法有效配置 | 未更換分工 |
| Jev | 可停用；不授權 claim/test/review/merge | 新 Campaign 要求停用 |
| Custom resource cost | trusted capability；session 不得刪除／降低已有成本 | 新增配置驗證 |
| Review、Sandbox、權限 | floors／原生配置保持有效 | 未降低 |

源碼改動會改變 `core_sha256`。舊 Queue 只能用其 frozen source 審計；不要將本輪
source 套到歷史 Queue、改 evidence hash 或重核發舊 intent。

## Multi-task Repo Adapter 與 Worker checks

`controller/repo-adapter.json` 可選 `campaign`：campaign_id、max_active、worker_budget、
review_budget、tasks。每 task 固定 task_hash、allowed_files、validators、worker_checks。
worker_budget 必須等於 task 數，task attempts=1；max_active 不得超過 2，且仍受 Repo
ceiling 約束。舊 marker 保持單 Worker／單 Review，不需要遷移。

Worker 開始前驗證固定契約及完整 pinned registry，取得 literal argv 指引。
最後修改後必須執行全部 worker_checks，作為最後一組工具呼叫。原生 CLI 的成功
command_execution events 必須精確符合 argv；文字、自報 JSON、substring、舊成功紀錄、
額外非 check commands 或最後 file_change 後缺檢查，均不能通過此 gate。
這是 Controller 在 native-trust 下觀察的執行證據，**不是 provider attestation**。
Controller 仍獨立重跑所有 validators，Review 仍由獨立 Astra 執行。

## Reviewed integration

`reviewed_batch` 核對 PASSED、review envelope、task/attempt/epoch、receipt、manifest、
policy、realm 及 artifact bytes。重複 ownership（即使 bytes 相同）、casefold/prefix conflict、
不同 base、tamper 或缺 Review 都拒絕。

`prepare_integration` 只向新 detached Worktree 組合已審 bytes；不修改 main/ref。
每個預期產物都核對 hash，實際 diff 不得超出 batch。未修改的合法 expected artifact
可保留。prepared receipt、完整 candidate tree 及 modes 固定保存，restart 重新驗證。

`NativeDevelopmentRunner.integrate` 重用原生 RPC validator path，合併並去重全部必要
checks（timeout 取更嚴者）。執行時保留全部合法容量；沒有 host fallback。
FAIL/UNKNOWN 設置 shared stop 與 durable `integration_failures`，重啟後 claim 及再次整合
均拒絕。只有程序清理已證實才能釋放實體 slots；釋放不會解除邏輯停損。
Build/Test 成功也不執行 merge。既有 `merge_validation` 的 conflict CLEAN 只是一項證據。

現有 dependency snapshot 對已存在 source 的覆寫保護仍保留；本輪不宣稱已支援任意
修改型 parent→child composition。遊戲首輪採兩個獨立 roots，之後由 Controller integration
明確依賴兩者 PASSED。既有 mock DAG 驗證與真實遊戲 DAG 成果分開報告。

## 可執行入口

`tools/repo_parallel_campaign.py` 是既有元件的薄層組合，不會建立/授權容量或配置。
由 Controller 在全新隔離 root 準備 source bundle、pinned Node/dependencies、adapter marker、
`controller/session.json`、`tasks.json`、`validator-registry.json`、`expected-stdout.json`。
所有 marker、contract、policy、registry、runtime hashes 必須一致。
所有 controller-only acceptance oracle 都須有固定 completion stdout，並綁定 readiness；
不能只用 exit 0 接納 Worker code 的 import-time exit。這不取代完整 artifact/test/review gate。

```sh
python3 -I -B tools/repo_parallel_campaign.py --root "$CAMPAIGN" --runtime "$RUNTIME" --prepare
```

prepare 是零 inference：檢查新 root、每 task native scope、Worker/Reviewer session start、
pinned baseline checks、project/scratch diff，再保存不可變 readiness。
**本輪未對新遊戲 Campaign 執行這個 prepare**；原 game cap 1 仍有效。

取得獨立人類授權及預算後，才可使用：

```sh
python3 -I -B tools/repo_parallel_campaign.py --root "$CAMPAIGN" --runtime "$RUNTIME" \
  --execute --worker-budget 2 --review-budget 2 --active-cap 2 \
  --authorization-reference "$HUMAN_AUTHORIZATION_REFERENCE"
```

authorization_reference 是可信 operator 的審計引用，不是密碼學人類身分證明。
參數本身不授權模型請求。exclusive execute-once marker、pinned exact budgets、zero retry
防止重啟重派；任何 FAIL/UNKNOWN 或 Review 不成立即停止。
完整 PASSED 後，native worker receipt/raw/process hashes 驗證兩個不同 CLI service 的
Controller 觀測重疊，再做 native integration checks 與 fresh restart custody。
這不聲稱 Provider 端推論同時性。

## 下一個有界遊戲 Campaign 提案（未授權、未執行）

來源：`monkey1sai/changshan-longdan @805db86f67ab2be152dea8abe57ca47f4e735fb7`。
獨立 task/attempt/evidence，不採用 06 未接納 candidate，不重用歷史額度。

| Task | 有價值的修改 | 精確寫入範圍 |
|---|---|---|
| A：ZIP entry 強化 | 拒絕危險 entry、保留合法 ZIP 與 Uint8Array TS contract | scripts/zip.mjs、tests/zip.test.ts |
| B：Packager 可測試入口 | 將既有打包流程抽成 `packageItch({distDir,outFile})`，預設 CLI 行為不變；支援 .tmp 的可重現相容性驗證 | scripts/package-itch.mjs、scripts/package-itch.d.mts、tests/package-itch.test.ts |

A/B 互無依賴、互不寫對方檔案，各用獨立 Worktree；都以 base 的既有 ZIP API 開發。
B 不修改 ZIP 演算法或 AGENTS/配置。A 不修改 packager。全部 Test/Typecheck/Build 通過
再各自獨立 Review；integration 明確等待 A、B 均 PASSED。

每 Worker 最後必跑 pinned Node 下的完整 Vitest、`tsc --noEmit`、Vite build。
Vitest 使用 configLoader native、maxWorkers=1、no-file-parallelism、threads；
Vite 使用 configLoader native、outDir=.tmp/build。Controller 獨立重跑並加 ZIP 負例 oracle；
組合後再跑完整 checks，並以 B 的 public API 將真實 build 輸出打包至 .tmp/release，
核對 ZIP entries/CRC/根 index 與 hash/custody。精確 argv 和 oracle 必須在執行前固定。

需要一次獨立授權：**2 Worker dispatch + 2 Review turns、零 attempt retry**；
只對新的隔離 campaign clone 明確批准 max_active=2，原 Repo/Global production 保持不動。
每 Worker 1 GiB/64 pids；同時至多兩個，review與integration序列；600 秒 supervisor 上限。
一般工具失敗維持原 3 次/首失敗起 60 秒的同 turn 修復；fatal/permission/timeout/
lease/fencing/UNKNOWN/預算超限立即停。所有停止與消耗 durable 保存，不因重啟重算。

本輪唯讀 WSL snapshot：Ubuntu-24.04、Codex CLI 0.161.0、10 logical CPUs、
MemAvailable=13227 MiB、swap used=0。僅資源盤點，非吞吐/速度/模型效能或執行授權。
外層 sandbox 的 Wsl/Service/E_ACCESSDENIED 在相同 owner-context 唯讀命令成功；
沒有修 ACL/隔離或用 host 執行 Worker。

## 驗證與擴充條件

本地驗收：2026-10-09 15:38 Asia/Taipei。下列全部為零 Provider；沒有 skipped。

| 命令／範圍 | 最終結果 |
|---|---|
| `python -B -m unittest discover -s orchestrator_tests -v` | **241 PASS**, 66.991s |
| `python -B -m unittest test_response_diagnostics test_decision test_phase2a test_resources test_combined test_inventory_safety` | **77 PASS**, 3.349s |
| cwd payload/jev: `python -B -m unittest test_inventory` | **12 PASS**, 0.027s |
| 合計 | **330 PASS**；原 302 保留，新增 28 |
| 新 CLI `--help`、多任務契約檢查 | PASS；不消耗 Worker/Review |
| 新遊戲 native prepare／Worker／Review／Build／integration | **NOT_RUN** |

新增測試涵蓋 priority/FIFO/eligibility、atomic quota、HELD/review資源占用、Repo ceiling、
prefix ownership、contract/restart drift、最後修改後的 literal Worker checks、完整 review
binding、合併產物 tamper/unchanged/conflicting owner、取消與 UNKNOWN capacity、整合
明確失敗後 claim/Review/restart 停損，以及 oracle exit0但缺completion marker拒絕。
既有 DAG review前不可接續、timeout/cancel/fencing/stale/清理/merge conflict 回歸均保留。
Mock DAG 的 controller peak inflight=2 有斷言；這不是新的真實 Codex 並行證據。

獨立唯讀 reviewer `resume_architecture` 終驗 **accept**，限本地 source checkpoint。
前三項 finding（integration持久停損、最後修改後checks、未修改artifact相容）及剩餘
Review dispatch入口均以 causal regression 修正；另覆核 oracle completion marker binding。
精確 tracked v3 diff SHA256=`76B87930197B6ED890D296AECED9D65B090F7B1C01902286CDA2DD0267A0560F`；
新 Campaign tool 終驗 SHA256=`0D48227059936BF8BD106F78D7E46C8BE83B9D29AA5731D27A669852D43E48C6`。
這是 advisory source review，不是 trusted Task Reviewer receipt／provider attestation。

Raw logs／精確 diff 在 ignored `runs/parallel-control-review/`；不將 private runtime、
evidence 或生成 fixture 提交。沒有新 real Campaign 或背景 Worker。

**DONE（source/offline）**：bounded parallel scheduling、Repo ceiling、multi-task adapter、
Worker-check gate、native integration code path、durable stop、metrics、regression與source review。
**PARTIAL**：Agent Factory真實遊戲並行與端到端交付。
**BLOCKED（待明確授權）**：新模型預算與隔離 clone capacity=2；原 Repo 仍1。
**NOT_RUN**：新native prepare/遊戲Campaign、Phase3、5/20Worker benchmark、remote/merge。

2→5→20 尚未開始。先完成新 Campaign 的完整驗收，再量測 queue wait、真實 CLI
interval、turn tokens、validation/review/integration 時間、retry/stop/conflict。
5/20 必須先有獨立容量與資源授權；本輪 hard cap 2 不變。1000 queued tasks 與
1000 simultaneous Workers 是不同條件，不將 queue contract test 當成容量 benchmark。
