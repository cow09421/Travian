# scheduler/loop.py 拆分出 action_dispatcher + sleep_manager

**Labels:** 可自動處理

## Parent

Architecture improvement - Candidate 3 (God Module)

## What to build

將 `scheduler/loop.py` 中的三個方法搬移到獨立模組。搬移時**不改寫邏輯**，純粹複製貼上後調整 import 與函數簽名。

### API 設計規格（已固定，實作時不需設計判斷）

**scheduler/action_dispatcher.py：**
```python
from playwright.async_api import Page

async def execute_single_action(
    page: Page,
    action_name: str,
    action_params: dict,
    state: dict,
) -> dict:
    """原 Scheduler._execute_single_action 的 module-level 版本。page 由呼叫者傳入（即 self.current_page）。"""

def filter_valid_actions(actions: list[dict], state: dict) -> list[dict]:
    """原 Scheduler._filter_valid_actions 的 module-level 版本。純函數。"""
```

**scheduler/sleep_manager.py：**
```python
async def smart_sleep(
    state: dict,
    consecutive_waits: int,
    min_sleep: int = 5,
    max_sleep: int = 60,
) -> int:
    """原 Scheduler._smart_sleep 的 module-level 版本。回傳睡眠秒數（caller 自行 await asyncio.sleep）。"""
```

### 執行步驟

1. 新建 `scheduler/action_dispatcher.py`
   - import 所有 executor 函數（目前 loop.py 已有的 import 全部搬過來）
   - 貼入 `_execute_single_action` 完整實作，改為 `async def execute_single_action(page, action_name, action_params, state)`
   - 貼入 `_filter_valid_actions` 完整實作，改為 `def filter_valid_actions(actions, state)`
2. 新建 `scheduler/sleep_manager.py`
   - 貼入 `_smart_sleep` 完整實作，改為 `async def smart_sleep(state, consecutive_waits, min_sleep, max_sleep)`
3. 更新 `scheduler/loop.py`
   - 刪除被搬移的三個方法實作
   - 刪除對應的 executor import（它們已移到 action_dispatcher.py）
   - 新增 import：`from scheduler.action_dispatcher import execute_single_action, filter_valid_actions`

      `from scheduler.sleep_manager import smart_sleep`
   - 呼叫處改為 module-level 函數呼叫（傳入 self.current_page 等參數）

**不作動清單：** `_auto_plan_next()` 和 `_get_current_state()` 保留在 loop.py（它們存取 self 狀態較深）。`_pre_loop_priority_checks()` 也保留在 loop.py（它同時是 Scheduler 方法，存取 self.current_page）。

## Acceptance criteria

- [ ] `scheduler/action_dispatcher.py` 存在，包含 `execute_single_action` 和 `filter_valid_actions`
- [ ] `scheduler/sleep_manager.py` 存在，包含 `smart_sleep`
- [ ] `scheduler/loop.py` 中已刪除三個被搬移的方法，改為 import + module-level 呼叫
- [ ] `_auto_plan_next()`、`_get_current_state()`、`_pre_loop_priority_checks()` 保留在 Scheduler 類別中
- [ ] syntax check 通過

## Blocked by

- #2a 刪除 executor/scout.py（避免 action_dispatcher 使用已被刪除的 import）