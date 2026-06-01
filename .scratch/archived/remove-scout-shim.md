# 刪除 executor/scout.py 薄轉發層

**Labels:** 可自動處理

## Parent

Architecture improvement - Candidate 5 (Shallow modules)

## What to build

`executor/scout.py` 只是一個 4 行的轉發函數，將 `send_scout` 委派給 `executor.attack.send_scout`。刪除此檔案，並將所有 `from executor.scout import send_scout` 改為 `from executor.attack import send_scout`。

## Acceptance criteria

- [ ] `executor/scout.py` 已刪除
- [ ] 全域搜尋 `from executor.scout import` 或 `import executor.scout` 的所有位置，全部改為 `from executor.attack import send_scout`
- [ ] `scheduler/loop.py` 的 import 已更新（目前未直接 import scout.py，但需 double check）
- [ ] 無其他檔案殘留對 `executor.scout` 的引用
- [ ] syntax check 通過

## Blocked by

None - can start immediately