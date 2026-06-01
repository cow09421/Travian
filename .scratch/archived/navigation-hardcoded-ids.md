# executor/navigation.py 硬編碼建築 ID

**Labels:** 已解決

## What to build

`url_map` 將 section 名稱映射到固定 `build.php?id=X` URL（如 barracks → id=19），假設建築永遠在同一個槽位。在 Travian Legends 中建築可放在任意槽位。

需要讓 `navigate_to` 接受可選的 `state` 參數，若有則從 `state.buildings_with_slots` 查找實際槽位。無 state 時仍用硬編碼作為 fallback。

## Acceptance criteria

- [ ] `navigate_to(page, section, sub_id, state=None)` 新增 `state` 參數
- [ ] 當 state 存在時，嘗試從 `buildings_with_slots` 解析實際 slot ID
- [ ] 所有呼叫 `navigate_to` / `navigate_to_build` 的地方檢查是否需要傳入 state
- [ ] 硬編碼 ID 作為 fallback 保留

## Blocked by

None - can start immediately