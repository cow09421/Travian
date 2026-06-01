# GameState 加入 TypedDict 文件化

**Labels:** 已解決

## What to build

遊戲狀態 dict 被 7+ 個模組消費但無型別定義。`has_plus` 欄位永遠是預設值（從未被設定），`map` 欄位設了但沒人讀。需加入 `GameState` TypedDict 作為單一來源文件，列出所有欄位名稱與型別。

## Acceptance criteria

- [x] `parser/state_builder.py` 加入 `GameState`、`Resources`、`BuildQueueItem` 等 TypedDict
- [x] 所有消費模組可直接 `from parser.state_builder import GameState` 參考

## Blocked by

None - can start immediately