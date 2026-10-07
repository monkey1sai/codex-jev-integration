# 離線驗證

測試保留既有 `payload/jev` 目錄結構。僅使用 Python 3.12 標準函式庫，測試中的 provider 回覆使用合成資料與 stub，不呼叫 TypeSafe，也不讀取憑證值。

在 repo 根目錄執行 PowerShell：

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -B -m unittest test_decision test_phase2a test_resources test_combined test_inventory_safety
```

預期 73 個測試。再於 `payload/jev` 執行：

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -B -m unittest test_inventory
```

預期 12 個測試，共 85 個。`PYTHONDONTWRITEBYTECODE` 同時傳給測試啟動的 Python 子程序，避免生成 pyc。

本次匯出驗證使用 `C:\Program Files\Python312\python.exe`：73/73 與 12/12 均通過。此結果只證明離線程式與測試的行為，不代表 Codex CLI、App 連線、付費推論、全域安裝或效能比較已通過。測試會建立並清理自己的暫存 fixtures；不應將暫存資料、cache 或 runtime journal 提交。
