# Jev tool / MCP / skill 候選選擇

新工作優先採用 2.2 的 `jev_decide` 與完整 context、跨種類候選背景和新版觀測；詳見 [具備背景的選擇](codex-jev-context.md)。
下文保留舊 `jev_select_resources` 介面契約；它仍可用，但僅短摘要不足以保證選對，且不寫新版日誌。

`jev_select_resources` 是既有 `jev_decision` MCP 的建議工具；`jev_route` 繼續選工作角色。兩者都不能執行任務、切換模型或授予權限。固定 TypeSafe endpoint、憑證解析與 timeout 沿用 [Codex/Jev](codex-jev.md)。

## 呼叫順序

1. Codex 先依 search-first 查 source、已裝能力及當前 runtime；明確規則或已指定資源直接使用。只有存在語意選擇需求才使用此工具。
2. tool 候選須為當前可呼叫工具；MCP 候選須描述實際可呼叫的 MCP 動作，不能只依配置中的 server 名稱；skill 須核對 canonical SKILL.md 存在及適用性。catalog 或配置列出不等於 runtime 可用。
3. 建立本地 ID → 實際工具／MCP 動作／skill 路徑對照。只傳公開或已授權傳 TypeSafe 的短摘要與去敏能力描述。不要傳私人 source、完整 skill、logs、對話、憑證、路徑或帳號識別資訊。
4. 使用者明確指定及適用規則強制的資源放 `required_ids`。`available` 及 `in_scope` 由 Codex 核對；兩旗標、返回的信心及模型建議均不是權限或驗收證據。
5. Jev 回傳 ID 後，Codex 對照本地表、重查可用性及授權，依選中的 skill 指引執行。不同種類的建議須由主控判斷是否重複、相容及需要排序，不能直接當作完整執行計畫。

## 輸入與選擇

沿用角色路由欄位：`workspace`、`task_summary`、`stage`、`large_plan`、`failure_count`、`risk_level`。workspace 是明確絕對工作區；risk 預設 governed。資源選擇一般使用 `stage=work`，真實 review checkpoint 不得為了選資源而改成 work。

- `candidates` 最多 24 個，包含 `id`、`kind`、`description`、`available`、`in_scope` 五個欄位。
- `id` 為 1–64 字元，使用英數及 `_.:-`，須唯一，保留值 `none` 不可用。ID 只是 alias，不是命令或檔案路徑。
- `kind` 是 `tool`、`mcp` 或 `skill`；description 是 1–240 字元的能力描述。
- `required_ids` 可省略；須唯一且全部在候選內。可指定同種類多個資源。

必要 review 優先於配置、API 與候選選擇。不可用或超出範圍的候選先排除；明確指定的候選不可用時回 `REQUIRED_RESOURCE_UNAVAILABLE`，交回主控，不自動替換。

每個尚未有 required 資源的種類提出一個 Choice 問題，包含 `none`；三種類合併成至多一次 HTTP 請求。模型至多選每種類一個 optional 候選。required 資源保持原樣，不由模型重新選擇；已有 required 的種類不再提出 optional 問題。

沒有剩餘問題時不讀 API 配置、不解析憑證、不呼叫 provider。停用、低信心、網路或回覆錯誤交回主控，保留可用的 required 資源。回覆嚴格核對問題、候選 ID、有限數值及機率分布；任一問題格式錯誤會丟棄全部 optional 建議。單次請求、不重試、不跟隨 redirect，request / response 各限 64 KiB。

以下是使用者已明確指定三類能力時的本地範例；ID 僅為示例，不能據此宣稱工具已存在：

```json
{
  "workspace": "/absolute/authorized/workspace",
  "task_summary": "Inspect a public documentation page with the explicitly requested capabilities.",
  "stage": "work",
  "risk_level": "bounded",
  "candidates": [
    {"id": "read_source", "kind": "tool", "description": "Read approved local task files", "available": true, "in_scope": true},
    {"id": "browser_snapshot", "kind": "mcp", "description": "Inspect an authorized browser page", "available": true, "in_scope": true},
    {"id": "official_research", "kind": "skill", "description": "Research using official sources", "available": true, "in_scope": true}
  ],
  "required_ids": ["read_source", "browser_snapshot", "official_research"]
}
```

此例返回三個 `source=required` 的 selected、`provider_called=false`、`executed=false`。需要模型判斷時只將明確指定的項目留在 required_ids；其餘 eligible 候選才可能送 TypeSafe。不能為測試方便擅自發送私人資料或新增付費推論。

## 生效、觀測與限制

目前 MCP server 版本為 2.2.0，tools/list 共六個工具（舊四個加 `jev_decide`、`jev_report_selection_outcome`）。現有工作階段可能仍使用已載入的舊 Python 程序及工具 schema；enabled_tools 亦須包含新工具。新建 Codex session／依支援方式重新連線後，須實際看到並呼叫工具才能宣稱該 session 可用。不能只因磁碟檔案更新就宣稱目前 session 已生效。舊 CLI `decision.py select-resources` 保持相容。

資源選擇回 `inventory_source=caller_reported`、`advisory_only=true`、`executed=false`。不掃描磁碟、不載入 skill、不安裝 MCP、不派工或執行。當前不寫既有角色路由 JSONL journal，回 `observation.status=not_recorded`，不可拿資源結果的 ID 呼叫 `jev_report_outcome`。角色路由與 2A 格式保持不變。

本地 mock、stdio MCP 及 CLI 檢查可以驗證介面與回退；不證明 TypeSafe 線上品質、成本、速度或實際資源執行成功。候選的去敏、授權、freshness 與 runtime 可用性仍由主控負責。此路徑不需要讀寫 Codex SQLite 或另啟 Codex executor。

官方 API 支援多個具名 Choice 問題及 `choice`、`confidence`、`probabilities` 回覆：[TypeSafe API](https://docs.typesafe.ai/api)、[Choice](https://docs.typesafe.ai/primitives/choice)。
