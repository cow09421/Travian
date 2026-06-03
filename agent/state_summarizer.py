from typing import Dict, Any
from parser.state_builder import GameState
from agent.knowledge_base import BUILDING_COSTS


def compress_state_for_llm(state: GameState) -> dict:
    """只傳 LLM 真正需要的資訊，砍掉 raw HTML 殘留、完整 map 等大欄位。"""
    return {
        "resources": state.get("resources", {}),
        "resource_rates": {
            k: state.get("resources", {}).get(k, 0)
            for k in ["wood_rate", "clay_rate", "iron_rate", "crop_rate"]
        },
        "buildings_summary": [
            {"slot": int(k), "gid": v.get("gid"), "level": v.get("level"), "name": v.get("name")}
            for k, v in state.get("buildings_with_slots", {}).items()
        ],
        "empty_slots": state.get("empty_building_slots", []),
        "resource_fields_summary": [
            {"slot": int(s), "type": f.get("field_type"), "level": f.get("level")}
            for s, f in state.get("resource_fields_by_slot", {}).items()
        ],
        "build_queue_full": state.get("build_queue_full", False),
        "build_queue": [
            {"name": q.get("name"), "seconds_left": q.get("seconds_left")}
            for q in state.get("build_queue", [])
        ],
        "troops_at_home": state.get("troops", {}).get("home", {}),
        "incoming_attacks": state.get("diplomatic_intel", {}).get("incoming_attacks", []),
        "population": state.get("population", 0),
    }


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

        # 1. 資源現況與生產速率 + 倉庫容量
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

        # 2. 當前建造佇列
        bq = state.get("build_queue", [])
        if bq:
            bq_str = ", ".join([f"{q.get('name', '?')} (剩 {q.get('seconds_left', 0)}秒)" for q in bq])
            parts.append(f"建造佇列: {bq_str}")
        else:
            parts.append("建造佇列: 空閒")

        # 3. 當前訓兵佇列
        tq = state.get("troop_queue", [])
        if tq:
            tq_str = ", ".join([f"{q.get('name', '?')} (剩 {q.get('seconds_left', 0)}秒)" for q in tq])
            parts.append(f"訓兵佇列: {tq_str}")
        else:
            parts.append("訓兵佇列: 空閒")

        # 4. 各建築等級（精簡：不分頁，只用一行）
        bld = state.get("buildings", {})
        if bld:
            bld_str = ", ".join(sorted([f"{n} Lv{l}" for n, l in bld.items()]))
            parts.append(f"建築: {bld_str}")
        else:
            parts.append("建築: 無")

        # 5. 資源田等級分布
        fields = state.get("resource_fields", {})
        min_fields = {}
        for ftype, flist in fields.items():
            if flist:
                min_lvl = min(f.get("level", 0) for f in flist)
                count = sum(1 for f in flist if f.get("level", 0) == min_lvl)
                min_fields[ftype] = f"最低 Lv{min_lvl} (共 {count} 塊)"
        if min_fields:
            parts.append(f"資源田: " + ", ".join([f"{k} {v}" for k, v in min_fields.items()]))

        # 6. 空地提示
        empty = state.get("empty_building_slots", [])
        if empty:
            parts.append(f"⚠️ 空地: {len(empty)} 個 slot 未建造 ({empty})")

        # 7. 英雄狀態
        hero = state.get("hero", {})
        if hero:
            hh = hero.get("hero_health", "?")
            hs = hero.get("hero_status", "?")
            parts.append(f"英雄: HP {hh}% 狀態 {hs}")

        # 8. 任務數量
        quests = state.get("quests", {})
        ready_quests = quests.get("total_reward_ready", 0)
        parts.append(f"可領取任務獎勵: {ready_quests} 個")

        return "\n".join(parts)

state_summarizer = StateSummarizer()
