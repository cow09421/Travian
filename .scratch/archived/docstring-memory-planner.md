# 補強 memory.py / planner.py 職責說明 docstring

**Labels:** 可自動處理

## Parent

Architecture improvement - Candidate 5 (Shallow modules)

## What to build

在 `agent/memory.py` 和 `agent/planner.py` 檔案頂部加入模組層級的 docstring，說明各自的職責範圍，幫助未來開發者理解這兩個模組的存在理由。

具體內容（以英文撰寫，與現有程式碼語言一致）：

**agent/memory.py：**
```
Short-term → long-term memory compression management.

Responsibilities:
1. Cache latest summary to avoid repeated DB queries (_summary_cache)
2. Monitor consecutive failures, trigger LLM-based compression (_compress_memory)
3. Expose get_summary() and record_action() only, hiding compression details
```

**agent/planner.py：**
```
Goal state machine management.

State transitions: set_goal() → advance_step() → complete_goal()
Persistence: DB read/write for crash recovery.
Navigation logic (advance_step, get_remaining_steps_text) lives here, not in the DB layer.
```

## Acceptance criteria

- [ ] `agent/memory.py` 頂部有 module-level docstring（純新增，不修改任何邏輯或 import）
- [ ] `agent/planner.py` 頂部有 module-level docstring（純新增，不修改任何邏輯或 import）
- [ ] syntax check 通過

## Blocked by

None - can start immediately