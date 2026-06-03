from typing import Dict, Any
from parser.state_builder import GameState
from agent.knowledge_base import BUILDING_COSTS

class StateSummarizer:
    def summarize_for_planning(self, state: GameState) -> str:
        """
        輸出一個緊湊的文字摘要，包含：
        1. 資源現況與生產速率（含負值警報）
        2. 倉庫/糧倉剩餘容量百分比
        3. 當前建造佇列（剩餘時間）
        4. 當前訓兵佇列
        5. 各建築等級（只列出可升級的，含升級成本）
        6. 資源田等級分布（只列出最低等級的幾個）
        7. 英雄狀態（在家/冒險中/生命值）
        8. 可領取的任務數量
        """
        if not state:
            return "No state data available."
        
        parts = []
        
        # 1. 資源現況與生產速率
        # 2. 倉庫/糧倉剩餘容量百分比
        res = state.get("resources", {})
        wood, clay, iron, crop = res.get('wood', 0), res.get('clay', 0), res.get('iron', 0), res.get('crop', 0)
        wh_cap = res.get('warehouse_cap', 800)
        gr_cap = res.get('granary_cap', 800)
        
        wh_pct_w = (wood / max(wh_cap, 1)) * 100
        wh_pct_c = (clay / max(wh_cap, 1)) * 100
        wh_pct_i = (iron / max(wh_cap, 1)) * 100
        gr_pct = (crop / max(gr_cap, 1)) * 100
        
        res_lines = [
            f"資源: 木{wood}({wh_pct_w:.0f}% +{res.get('wood_rate', 0)}/h), "
            f"土{clay}({wh_pct_c:.0f}% +{res.get('clay_rate', 0)}/h), "
            f"鐵{iron}({wh_pct_i:.0f}% +{res.get('iron_rate', 0)}/h), "
            f"糧{crop}({gr_pct:.0f}% +{res.get('crop_rate', 0)}/h)"
        ]
        if res.get('crop_rate', 0) < 0:
            res_lines.append("⚠️ 警告: 糧食生產為負！")
        parts.append("\n".join(res_lines))
        
        # 3. 當前建造佇列
        bq = state.get("build_queue", [])
        if bq:
            bq_str = ", ".join([f"{q.get('name', '?')} (剩 {q.get('seconds_left', 0)}秒)" for q in bq])
            parts.append(f"建造佇列: {bq_str}")
        else:
            parts.append("建造佇列: 空閒")
            
        # 4. 當前訓兵佇列
        tq = state.get("troop_queue", [])
        if tq:
            tq_str = ", ".join([f"{q.get('name', '?')} (剩 {q.get('seconds_left', 0)}秒)" for q in tq])
            parts.append(f"訓兵佇列: {tq_str}")
        else:
            parts.append("訓兵佇列: 空閒")
            
        # 5. 各建築等級
        bld = state.get("buildings", {})
        bld_parts = []
        for bname, level in sorted(bld.items()):
            next_lvl_cost = BUILDING_COSTS.get(bname, {}).get(level)
            if next_lvl_cost:
                bld_parts.append(f"{bname}: Lv{level} (升級需 木{next_lvl_cost['wood']} 土{next_lvl_cost['clay']} 鐵{next_lvl_cost['iron']} 糧{next_lvl_cost['crop']})")
            else:
                bld_parts.append(f"{bname}: Lv{level}")
        parts.append("現有建築:\n  " + "\n  ".join(bld_parts))
        
        # 6. 資源田等級分布 (找出最低等級的)
        fields = state.get("resource_fields", {})
        min_fields = {}
        for ftype, flist in fields.items():
            if flist:
                min_lvl = min(f.get("level", 0) for f in flist)
                count = sum(1 for f in flist if f.get("level", 0) == min_lvl)
                min_fields[ftype] = f"最低 Lv{min_lvl} (共 {count} 塊)"
        parts.append(f"資源田分布: " + ", ".join([f"{k}: {v}" for k, v in min_fields.items()]))
        
        # 7. 英雄狀態
        hero = state.get("hero", {})
        if hero:
            hero_health = hero.get("hero_health", "?")
            hero_status = hero.get("hero_status", "?")
            parts.append(f"英雄: 血量 {hero_health}%, 狀態 {hero_status}")
            
        # 8. 任務數量
        quests = state.get("quests", {})
        ready_quests = quests.get("total_reward_ready", 0)
        parts.append(f"可領取任務獎勵: {ready_quests} 個")

        return "\n".join(parts)

state_summarizer = StateSummarizer()
