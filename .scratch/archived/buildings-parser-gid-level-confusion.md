# buildings.py class 解析混淆 GID 與等級

**Labels:** 已解決

## What to build

`parser/buildings.py` 原本的 class 解析中 `re.search(r'g(\d+)', cls)` 被當成等級（level），但 class 格式 `buildingSlot a19 g23 aid19 roman` 中的 `g23` 是 **GID（建築類型）** 不是等級。等級完全不存在於 class 中，需從子元素 `.level` 提取。

此 Bug 導致建造列表永遠是空的（g23 被當成 level=23，通過了 `level > 0` 檢查但 name lookup 用 aid 而不是 gid，所以名稱對不上）。

## Acceptance criteria

- [x] `g(\d+)` 正確解讀為 GID
- [x] 等級從 `el.select_one('.level').get_text()` 取得
- [x] `AID_TO_NAME` 用 GID 查詢名稱
- [x] `gid == 0` 或 `level == 0` 視為空槽位

## Blocked by

None - can start immediately