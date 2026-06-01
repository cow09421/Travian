# executor/attack.py 缺少 navigate_to_build import

**Labels:** 已解決

## What to build

`executor/attack.py` 呼叫 `navigate_to_build(page, 39)` 在兩處（line 29, 115）但從未 import 它。首次執行 `send_attack()` 或 `send_scout()` 時會噴 `NameError`。

## Acceptance criteria

- [x] 已在檔頂加上 `from executor.navigation import navigate_to_build`

## Blocked by

None - can start immediately