# 訓兵找不到 Phalanx 輸入框

**Labels:** 已解決

## What to build

`executor/train.py` 呼叫 `navigate_to_build(page, 19)` 假設 Barracks 在槽位 19，但 Travian Legends 的建築槽位不固定。需先從 `state.buildings_with_slots` 或掃描 dorf2 頁面取得正確槽位 ID。

此外，訓練輸入框的選擇器僅試 `input[name='t1']`，Travian Legends 可能用其他名稱。需嘗試 9 種選擇器，失敗時截圖 + 列出頁面所有 input。

## Acceptance criteria

- [x] `train_troops` 改為先用 `state.buildings_with_slots` 查槽位
- [x] 新增 `_find_building_slot_from_page()` 掃描 dorf2
- [x] 新增 `_find_troop_input()` 嘗試 9 種選擇器
- [x] `parser/buildings.py` 修正 class 解析（`g(\d+)` 是 GID 不是等級）
- [x] `parser/buildings.py` 加上 `.level` 子元素提取等級

## Blocked by

None - can start immediately