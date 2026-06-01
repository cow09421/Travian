# Travian Legends 核心機制

## 建造隊列
- 免費帳號：同時只能建造 1 個（資源田或建築）
- Plus 帳號：資源田和建築可各一個同時進行
- 新玩家保護期：無法攻擊他人，也無法被攻擊

## 資源田
- 18 塊田：木材x4、黏土x4、鐵x4、糧食x6
- slot_id 從 1 開始，1-18 對應 dorf1 的各個格子
- 升級成本隨等級指數增長（每級約翻倍）
- 糧食田是最重要的，因為人口和軍隊都消耗糧食
- 資源田最高 Lv12，Lv10 後費用極高

## 倉庫/穀倉
- Warehouse：儲存木材、黏土、鐵
- Granary：儲存糧食
- 升級倉庫是前期重要任務（避免資源浪費）
- 預設容量 800，升級後增加
- Warehouse Lv10 容量 11000

## 人口系統
- 每個建築佔用 1 人口（建造後永久）
- 每個士兵駐紮時消耗 1 人口
- 人口上限由 Residence（Lv1-10: 20-200）或 Palace 決定
- 人口超過上限：糧食消耗激增（惡作劇稅）

## 建築前置條件速查
- Barracks: Main Building Lv3
- Stable: Main Building Lv5, Barracks Lv3
- Academy: Main Building Lv3, Barracks Lv3
- Smithy: Academy Lv1, Main Building Lv3
- Marketplace: Main Building Lv3, Warehouse Lv1, Granary Lv1
- Town Hall: Main Building Lv10, Academy Lv10
- Sawmill/Brickyard/Iron Foundry: Main Building Lv5 + 對應田 Lv10
- Grain Mill: Main Building Lv5 + Crop Field Lv5
- Hero's Mansion: Rally Point Lv1, Main Building Lv3

## 第二村條件
- 文化點 > 200（舉辦慶典可快速累積）
- 3 個殖民者（Settler，需 Residence Lv10）
- 找到無主村或低人口村作為殖民地

## 劫掠效率
- 劫掠效率 = 兵力負重 / 來回時間
- 高盧 Theutates Thunder 負重 75、速度 19，是最佳劫掠騎兵
- 劫掠時保留 20% 兵力在家防守

## Cranny（藏糧窖）重要性
- Lv1: 保護 200 資源（全類型加總）
- Lv10: 保護 2200 資源
- 被強玩家威脅時：優先升 Cranny 到 Lv5-10

## Main Building 加速
- 等級越高，建造速度越快
- Lv1：標準速度，Lv10：快 33%，Lv20：快 60%

## 英雄
- 英雄死後可在 Hero's Mansion 復活
- 前期屬性點建議加 Resources（+4/點產量）
- 有軍事目標時改加 Fighting Strength
- 英雄冒險可獲得資源和裝備