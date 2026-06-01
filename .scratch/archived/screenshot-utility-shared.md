# 截圖功能移至 BrowserManager 共用

**Labels:** 可自動處理

## Parent

Architecture improvement - Candidate 6 (Speculative)

## What to build

將目前分散在 `executor/build.py`、`executor/hero.py`、`executor/quests.py` 三處重複的 `_take_screenshot` 私有函數，集中到 `scraper/browser.py` 的 `BrowserManager` 類別中作為公開方法。

現有重複程式碼模式：
```python
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
path = config.screenshots_dir / f"{prefix}_{ts}.png"
try:
    await page.screenshot(path=str(path))
except Exception:
    pass
```

**不作動清單：** 不修改 `executor/attack.py` 和 `executor/train.py` 中的截圖（它們使用 inline 寫法且無共用函數包裝，為降低變更範圍暫不動）。僅移除明確有 `_take_screenshot` 私有函數的三個檔案。

## Acceptance criteria

- [ ] `BrowserManager` 新增 `async def take_screenshot(self, page: Page, prefix: str) -> str | None` 方法，成功回傳路徑、失敗靜默回傳 None 不拋例外
- [ ] `executor/build.py` 的 `_take_screenshot` 刪除，所有呼叫改為 `await browser_manager.take_screenshot(page, prefix)`
- [ ] `executor/hero.py` 的 `_take_screenshot` 刪除，所有呼叫比照辦理
- [ ] `executor/quests.py` 的 `_take_screenshot` 刪除，所有呼叫比照辦理
- [ ] 三個檔案 syntax check 通過 (`python -c "import ast; ast.parse(open('...').read())"`)
- [ ] `executor/attack.py` 和 `executor/train.py` 的 inline 截圖保持不變

## Blocked by

None - can start immediately