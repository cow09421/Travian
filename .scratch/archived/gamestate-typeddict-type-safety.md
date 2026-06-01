# GameState TypedDict 啟用類型安全

**Labels:** 可自動處理

## Parent

Architecture improvement - Candidate 4 (GameState TypedDict zero type safety)

## What to build

`parser/state_builder.py` 已有完整的 `GameState` TypedDict 定義，但沒有任何 consumer import 它——所有 consumer 都使用 `state: dict`，導致鍵值拼寫錯誤只能在執行期發現。

本次變更：
1. 在 `parser/state_builder.py` 中新增巢狀 TypedDict：`HeroState`、`QuestState`、`DiplomaticIntel`
2. 在 `GameState` 中補上巢狀型別（取代目前的 `hero: dict` / `quests: dict` / `diplomatic_intel: dict`）
3. 在 `agent/decision.py` 的函數簽名中將 `state: dict` 改為 `state: GameState`
4. 在 `agent/knowledge_base.py` 的 `get_new_building_recommendation` 簽名中將 `state: dict` → `state: GameState`
5. 在 `agent/intel.py` 的 `get_diplomatic_intel` 簽名中將 `state: dict` → `state: GameState`
6. 在 `scheduler/loop.py` 的 `_get_current_state` 回傳型別從 `Optional[dict]` 改為 `Optional[GameState]`

**不作動清單：** `executor/train.py` 的 `state: dict = None` 保持不變（該參數是選擇性的，且來自不同層）。

## Acceptance criteria

- [ ] `HeroState` TypedDict 存在並包含 `hero_health`（int|None）、`hero_xp`（int）、`hero_level`（int）、`hero_available_points`（int）、`hero_status`（str）、`hero_items`（list）、`hero_adventures`（list）、`hero_resource_rewards`（dict[str,int]）
- [ ] `QuestState` TypedDict 存在並包含 `daily_quests`（list）、`main_quests`（list）、`total_reward_ready`（int）
- [ ] `DiplomaticIntel` TypedDict 存在並包含 `raid_targets`（list）、`threats`（list）、`neutrals`（list）、`scout_priority`（list）、`summary_text`（str）、`new_player_protection`（bool）、`protection_hours_remaining`（float）
- [ ] `GameState.hero` 改為 `HeroState`（取代 `dict`）
- [ ] `GameState.quests` 改為 `QuestState`（取代 `dict`）
- [ ] `GameState.diplomatic_intel` 改為 `DiplomaticIntel`（取代 `dict`）
- [ ] 4 個 consumer 檔案的 import 和函數簽名已更新
- [ ] syntax check 通過（mypy 不強制，但 ast.parse 通過）

## Blocked by

None - can start immediately