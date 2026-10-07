# Codex / Jev 角色與資源選擇

2.2 新增 `jev_decide`，以足夠的目標、環境、限制、證據及候選差異合併角色／資源 Choice；
缺背景時先補資料，信心不能代替充分性。新版 observation/outcome 與本機 inventory helper 見 [具備背景的選擇](codex-jev-context.md)。

2A 新增可觀測建議、呼叫端回報與離線評估。操作及資料界線見本 repo 的 [行為與驗證說明](../README.md)。不自動分派；本檔對齊日常 risk delivery 例外，其他審查、API、資料與權限界線不變。風險分類、派工及有效 App 配置須遵循呼叫端自身的規則。

`jev_select_resources` 新增 tool、MCP 與 skill 的候選選擇。Codex 先查現有能力及實際可用性；需要語意選擇時才送已去敏、可傳 TypeSafe 的候選。使用者明確指定的資源列入 `required_ids`，不可由模型替換。候選格式、回退及新 session 載入見 [資源選擇](codex-jev-resources.md)。

全域模型與角色設定屬於使用者的 `~/.codex`；專案設定屬於該工作區自己的 `.codex`。Codex 支援的優先序為 CLI → 受信任工作區 → profile → global。既有工作階段不因檔案變更自動切換，必須依支援方式載入並觀察實際 runtime。

| 用途 | 角色 | 實值來源 |
|---|---|---|
| 主控與整合 | default / build_local | 有效 config/profile/App session/runtime；日常採配置預設 |
| 本機探勘／官方研究 | explorer / researcher | 有效 role TOML、repo override、dispatch runtime |
| 範圍明確的實作／診斷 | worker / dev / debugger | 有效 profile/role、repo override、dispatch runtime |
| 架構與獨立審查 | architecture_reviewer / reviewer / requirements / security aliases | 核對所需獨立角色、model/effort 與 runtime；checkpoint 不變 |

CLI 數值或模型路由建議僅 advisory，不覆寫 App/runtime。複雜工作可明確選擇較高 effort；不能因配置檔或建議變動聲稱既有 session 已切換。CLI `codex -p build_local` 不證明 App 選了該 profile。

## 分派與審查

- 大型規畫前、同一問題失敗至少兩次，仍安排獨立 `architecture_reviewer`；大型計畫交付亦保留此審查。governed（G/S）交付前保留獨立 risk review，依風險選匹配 reviewer；builder 不能自審。保留原重試預算，不靠模型升級重新計數。
- 準備分派有語意判斷的工作時使用可呼叫的 `jev_route`。提供明確 workspace、已去敏且可傳 TypeSafe 的短摘要及真實 stage、large_plan、failure_count、risk_level。不傳憑證、私人 source、完整 logs 或對話。工具不可用、停用或失敗不阻止已有證據與授權支持的交付，必要獨立 review 仍須履行。
- `risk_level` optional enum 為 `low` / `bounded` / `governed`，省略預設 `governed`：舊 caller 的交付 review 不變。敏感、repo-required-review 或不確定任務使用 governed。非法 enum/type 是 input error，不能降級或送 API；工具不驗證呼叫端風險真偽。
- 必要 review 規則先於 API：`before_plan` 且 large_plan、failure_count >= 2、或 `before_delivery` 且 governed/large_plan，回 required_review=true 且 provider_called=false；停用／失效不取消 checkpoint。
- `before_delivery` 且 low/bounded、large_plan=false、failure_count < 2，回 `LOCAL_VERIFICATION_REQUIRED`、provider_called=false、required_review=false。仍須主控完成 local deterministic checks、repo gates/sign-off 與 concrete human authorization；只免全域例行 delivery architecture review。其餘語意工作由 API Choice 建議，低信心／缺憑證／錯誤回主控。
- `jev_status` 只列設定及憑證名稱存在性，不讀 key 值。`jev_route` 在 API 呼叫內部解析 process environment 或同一使用者 HKCU 的 `TYPESAFE_API_KEY`，不寫檔、不輸出。
- 工具只給建議，不啟動 agent、不切換模型、不執行命令、不授予 approval。協調者依現有授權挑選角色，核對實際 model/effort。沒有相符能力時回報 UNVERIFIED，不靜默替換。
- 這是 MCP 輔助層和協調規則，並非機器強制的 approval gate。Hooks 維持停用。工具尚未載入時回報缺口，再依全域/工作區角色設定分派；不能宣稱 Jev 已生效。
- 簡單命令、格式化、已確定的規則與數值計算直接在程式執行。需要可見瀏覽器的驗收依專案規則另行處理；Jev 信心不代表 PASS。

觀測維持既有 journal schema：新增固定 reason `LOCAL_VERIFICATION_REQUIRED`，不新增 risk field。不得從舊 observation 列推回 risk_level；caller_reported、reason 或 confidence 均不證明風險分類正確、任務執行、checks PASS、approval 或 review 完成。資料／容量／回報／離線證據界線見 [觀測契約](codex-jev-context.md)，原有界線不變。

## 全域與工作區設定

全域 JSON：`~/.codex/jev/config.json`。每次工具呼叫僅讀明確 workspace 下的 `.codex/jev.json` 覆寫（不往父目錄搜尋，也不修改全域）。路由欄位：`enabled` 布林、`confidence_threshold` 有限 0–1、`timeout_seconds` 有限 1–20 秒。另有獨立驗證的 `observability`；非法觀測設定只停止記錄。未知路由欄位與非法路由型別停止 API；工作區不能改 endpoint 或憑證來源。

```json
{"enabled": true, "confidence_threshold": 0.9, "timeout_seconds": 10}
```

單一工作區停用 API，保留工具狀態和必要審查：

```json
{"enabled": false}
```

存到 `<workspace>/.codex/jev.json`。全域停用則將 `~/.codex/jev/config.json` 的 `enabled` 改為 false；特定工作區可明確 enabled=true 覆寫。設定每次呼叫重讀，不需重啟 MCP。

完整停用該工作區 MCP（新 session 生效）：在 `<workspace>/.codex/config.toml` 合併以下段落，保留原有設定。

```toml
[mcp_servers.jev_decision]
enabled = false
```

模型也可以工作區自己的 `.codex/config.toml` 覆寫；角色可在 `.codex/agents` 使用原生 Codex 設定。全域角色值是預設，工具回傳的 model/effort 亦是預設建議，工作區生效值由 Codex runtime 決定。不能靠 JSON 降低權限、取消審查或延長重試預算。

## 回退

本 repo 只版本化可移植的 runtime 與測試，不包含先前機器專用的安裝／回退候選、命令或備份。全域安裝須另以精確 manifest、經驗證的備份及受審命令完成；發現 hash、身分或權限漂移時停止，不覆蓋後續修改。

維護完成或回退後重新跑適用 CLI health、MCP 與設定讀回，並驗證實際 session；不操作登入、不啟用 hooks，也不以修改 ACL 或 sandbox 修復環境錯誤。整批多檔操作不能只因單檔 rename 成功就宣稱原子。

## 官方來源與邊界

- [Codex config precedence](https://learn.chatgpt.com/docs/config-file/config-basic)
- [Codex config reference](https://learn.chatgpt.com/docs/config-file/config-reference)
- [TypeSafe HTTP API](https://docs.typesafe.ai/api)
- [TypeSafe Choice](https://docs.typesafe.ai/primitives/choice)

固定 endpoint `https://api.typesafe.ai/v1/systemone`；provider model `jev-latest`；一次請求、不重試、不跟隨 redirect、64 KiB 回覆上限。Timeout 是 HTTP socket timeout，並非整次調用的嚴格 wall-clock 上限，Codex MCP tool timeout 另設 25 秒。0.8 threshold 尚未經個人任務資料校準，不代表品質改善已被證明。
