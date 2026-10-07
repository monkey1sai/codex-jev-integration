# Jev 2.2：具備環境背景的角色與資源選擇

`jev_decide` 合併角色與 tool / MCP / skill 的建議選擇，只使用 Choice。
它不執行任務、不派工、不切模型、不授權。舊的 `jev_route`、`jev_select_resources` 與角色觀測保持相容。

## 何時使用

先由 Codex 查實際能力、來源及適用規則。已指定或可用規則決定的選擇直接處理。
有語意歧義且資料允許傳 TypeSafe 時，使用 `jev_decide`；角色已確定則設 `select_role=false`。
本機工具 `inventory.py` 能將 caller runtime snapshot 與明確 resource specs 組成候選。
它不是 Codex runtime 探索器：工具清單、範圍、候選說明仍由 caller 提供。

## 避免稀疏上下文

上下文不足，即使 Jev 高信心也可能選錯。不能把字數多、欄位齊全或高信心当作正確證據。
`context` 包含以下欄位：

- `goal`：這一步需要完成的目標。
- `success_criteria`：可區分完成與未完成的條件。
- `environment`：影響選擇的 runtime、工具狀態與目前位置。
- `constraints`：這一步的實際限制；無限制時用空列表。
- `evidence`：已觀察的必要事實，不用猜測填空。
- `unknowns`：非關鍵未知；無則空列表。
- `critical_unknowns`：答案可能改變選擇的關鍵未知；非空就先返回 Codex 補資料。

候選包含 `id/kind/description/available/in_scope/when_to_use/limits/requires/conflicts`。
`requires` 與 `conflicts` 使用候選 ID；它們是呼叫端宣告的明確關係，不能完整表達任意相容性。
所有 eligible 候選、required IDs 與同一份 context 都放在共享 state 中。
不將完整 inventory 輸出、local_bindings、原始路徑、完整私人 source/logs/對話或憑證送給 TypeSafe。
`inventory={captured_at,version}` 使用本機 snapshot 時間與 SHA-256；最大 age 300 秒，未來容忍 5 秒。
時間與 hash 是 caller metadata，不證明資料真實或完整；執行前仍核對實際可用性與授權。

## 選擇與回退

必要 review / local verification gate 仍先於配置與 API；既有 input error 與 gate 契約保留。
指定資源先保留；不可用或超出範圍的指定資源返回明確缺口。
沒有 optional 問題且角色已確定時，不需 provider。
缺必要 context 或有 critical unknown 時，本機返回 `INSUFFICIENT_CONTEXT`，不呼叫 API。
結構完整只表示可以詢問；模型仍需回答獨立的上下文充分性 Choice。

一次請求可以包含 context、role 與各類 resource Choice。各題不能看到其他題的答案。
若 context 判為不足或不確定，全部 optional 選擇不採用；指定資源保留，交回 Codex。
任一回答格式非法，全部 optional 建議丟棄；低信心或明確相依/衝突不滿足也回退。
同批 optional 問題已提交 provider，丟棄結果不代表沒有產生費用。
維持單次請求、不自動重試、不跟隨 redirect、request/response 各 64 KiB 上限。
輸出都是 advisory，`executed=false`；confidence 不代表正確率、完成或批准。

## 本機觀測

`jev_decide` 使用獨立 schema 2 journal：`~/.codex/jev/audit/resource-decisions.jsonl`。
透過 `jev_report_selection_outcome` 回報同 workspace、同 observation ID 的結果。
相同回報冪等；衝突拒絕。不能把這個 ID 送給舊 `jev_report_outcome`。
舊角色 journal schema 1 不遷移；舊 `jev_select_resources` 仍不寫觀測，新的 resource-only 呼叫使用 `jev_decide(select_role=false)`。

記錄去識別 workspace hash、隨機 observation ID、模式、固定原因、context 狀態、所選 alias 的 hash/kind/source、
路由、provider model/usage、耗時、inventory hash。沒有任務摘要、context、候選說明、binding 或原始路徑。
Hash 可以連結同一值，低熵名稱也可能被猜回；不宣稱匿名或以此允許儲存秘密。
結果包含 adopted/result/tool_calls/rework_count/reported_model 與耗時；全部為 `caller_reported`，`execution_verified=false`。
實際測試證據另存任務檔案，不把 caller 的 completed 升格為驗收通過。

沿用 observability 開關及 workspace 只能縮限的設定。新 journal 獨立上限是 min(全域 max_records,250)
與 min(全域 max_bytes,512 KiB)，不自動輪替。原角色 journal 的 1000/2 MiB 上限保持不變。
兩份 journal 的容量分開計算；全開時最大合計 1250 筆／2.5 MiB。鎖、no-follow 與 Windows handle 保護重用既有實作。
觀測滿額、鎖衝突或資料損壞只停止觀測，不取消原有審查或授權要求。

## 生效與驗收

MCP server 2.2.0 共六個工具；全域 enabled_tools 必須包含完整工具名。
磁碟修改不會更新既有長駐 session；使用支援的新 session / 重新連線並實際呼叫後，才有原生 runtime 證據。
本機 stdio smoke、mock tests、原生 MCP 調用與完整任務比較分開報告。
本版沒有快取建議、沒有自動 executor，也沒有啟用上下文排序、錯誤診斷或交付證據核對。

全域安裝的寫入由具體 manifest 與一次受審命令約束；日常 CLI/App 保留 workspace sandbox、on-request 與 auto-review。
MCP 程式載入不要求把整個全域程式目錄加入日常寫入範圍；自訂 permission 草案的啟用另須核對有效配置。
先前的機器專用維護 installer（不包含於本 repo）使用持續持有的檔案/祖先 handle、精確 hash/ACL、固定備份及 journal。
stage 在目的檔案的同一目錄以 CREATE_NEW 建立，持續持有 exclusive handle；既有目的檔案的完整 owner/group/ACL 相符後才寫內容。
備份與 journal 是建立時即受保護的新檔案，核對自身保護規則與內容 hash；回滾使用保留的原始物件及其原 file ID/ACL，不從內容副本重建權限。
既有檔案先保留原物件，再以 no-replace rename 發布已驗證 stage；每次 rename 原子，但兩次之間原路徑短暫缺席，整批也不具原子性。
若遇其他檔案佔用、身分或 hash/ACL 漂移，停止並保留原物件，不覆蓋其他修改。
CLI 設定讀回、CLI MCP 實際呼叫及目前 App session 載入是三項不同證據；共用 config.toml 不代表既有 App 已重連。

官方依据：[State](https://docs.typesafe.ai/concepts/state)、[Choice](https://docs.typesafe.ai/primitives/choice)、[API](https://docs.typesafe.ai/api)。
