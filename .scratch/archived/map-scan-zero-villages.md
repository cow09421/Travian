# 地圖掃描永遠回傳 0 個村莊

**Labels:** 已解決

## What to build

`parser/map_scanner.py` 的 `scan_map_with_js()` 因 karte.php 使用 PixiJS Canvas 渲染（SPA），4 秒內地圖 tile 資料根本還沒載入。需改用 `/statistics/village` RESTful API 透過 BeautifulSoup 解析村莊表格取得座標。

另需修正統計頁面 URL（`/statistiken.php` → `/statistics`、`/berichte.php` → `/report/overview`），以及處理村莊分頁的 HTML 結構（`td.coords a[href*="karte.php?x=&y="]`）。

## Acceptance criteria

- [x] 從 `/statistics/village?page=N` 成功解析 20+ 村莊/頁
- [x] 正確提取玩家名（`td.pla`）、人口（`td.hab`）、座標（`td.coords a`）
- [x] URL 修正：`navigation.py`、`intel.py`
- [x] `_scan_via_statistics` 移除過嚴距離過濾

## Blocked by

None - can start immediately