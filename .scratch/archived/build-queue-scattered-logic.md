# 建造隊列已滿邏輯散落三處需集中

**Labels:** 已解決

## What to build

「建造隊列是否已滿」的判斷公式 `len(bq) >= (2 if has_plus else 1)` 獨立計算於三個地方：`agent/decision.py`、`scheduler/loop.py`（`_filter_valid_actions`）、`scheduler/loop.py`（`_main_loop`）。已導致一次 Bug（decision.py 漏檢查）。

需集中到 `parser/state_builder.build_game_state()` 中計算一次，存入 `state["build_queue_full"]`，其他模組直接讀取。

## Acceptance criteria

- [x] `state_builder.py` 加入 `build_queue_full` 欄位
- [x] `decision.py` 改讀 `state.build_queue_full`
- [x] `loop.py` 兩處改讀 `state.build_queue_full`

## Blocked by

None - can start immediately