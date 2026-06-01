import json
from typing import Optional, TYPE_CHECKING
if TYPE_CHECKING:
    from parser.state_builder import GameState

from loguru import logger

from agent.llm_client import llm_client
from agent.planner import planner
from agent.memory import memory_manager
from agent.knowledge_base import knowledge_base, BUILDING_COSTS
from database import db


AUTONOMOUS_SYSTEM_PROMPT = """你是 Travian Legends 的 AI 玩家。你的目標是讓村莊持續變強。

你可以自由探索策略。沒有固定「正確」做法——根據局勢判斷價值。
可以升資源田、蓋建築、訓兵、偵察、劫掠，或同時規劃多件事。
唯一要求：每輪都要有實際行動，不要無謂等待。

## 當前遊戲狀態
{state}

## 你現在可以做的事
{available_actions}

## 技術限制
- 建造隊列：{queue_status}
- 資源是否夠建造請參考可用行動清單

## 英雄狀態
{hero_status}

## 任務與每日任務
{quest_status}

## 周遭地圖情報
{map_intel}

## 近期行動紀錄
{recent_actions}

## 長期記憶
{memory}

## 策略筆記
{strategy_notes}

## 外交情報與戰略態勢
{diplomatic_intel}

### 外交決策規則
根據上方情報，按以下規則做出判斷：

**劫掠條件**（同時滿足才執行）:
- 我方新手保護期已結束
- 有兵力在家（home troops > 0）
- 目標是無主村，或已偵察確認資源豐富的低人口村
- 每次出兵保留至少 20% 兵力在家防守

**偵察條件**:
- 有偵察兵（Pathfinder/Equites Legati/Scout）
- 目標人口 < 200 且距離 < 20 格
- 尚未在近 48 小時內偵察過

**威脅應對**:
- 人口 > 我方 3 倍且距離 < 5 格 → 優先升 Cranny 保護資源
- 同盟成員 → 不攻擊，可以忽略
- 無法判斷 → 觀察，繼續發展

**嚴禁行為**:
- 新手保護期內不執行任何軍事行動
- 不攻擊人口超過我方 2 倍的村莊（兵力不對等）
- 不在兵力全部在外時留家空防

## 決策思考框架（每輪都要過一遍）
在選建造動作之前，先在腦中回答：
1. 目前最大的瓶頸是什麼？（資源快滿？沒有兵舍？隊列閒置？）
2. 建造隊列空閒時，按以下優先順序決定行動：
   a. 有待領取的任務獎勵？→ collect_quest_reward（最優先，免費資源）
   b. 英雄有待轉移的資源？→ collect_hero_resources  
   c. 資源田某類嚴重落後？→ upgrade_resource_field
   d. 有強力推薦的新建築（知識庫標記 high priority）？→ upgrade_building（新建）
   e. 現有建築等級太低是瓶頸？→ upgrade_building（升級）
   f. 以上皆無 → 升一個最便宜的資源田維持成長
3. 我有兵力可以出征嗎？有的話有沒有值得偵察/劫掠的目標？
然後選 1 個建造動作（如果隊列空）+ 0-1 個非建造動作。

## 提醒
{nudge}

## 輸出規則
直接輸出工具呼叫，不需要解釋。隊列空閒就給 1 個建造動作，可同時加訓兵等其他動作。"""


class AutonomousBrain:

    def _build_available_actions(self, state: GameState) -> str:
        buildings = state.get("buildings", {})

        build_queue_full = state.get("build_queue_full", False)
        bq = state.get("build_queue", [])

        if build_queue_full:
            remaining = bq[0].get("seconds_left", 0) if bq else 0
            name = bq[0].get("name", "?") if bq else "?"
            lines = [f"【建造隊列已滿】正在建造 {name}，剩 {remaining} 秒。"]
            lines.append("本輪請選擇非建造動作：訓兵、偵察、劫掠等。")

            tq = state.get("troop_queue", [])
            if not tq and "Barracks" in buildings:
                lines.append("【訓兵】兵舍空閒，可訓練部隊（train_troops）")
            elif not tq and "Stable" in buildings:
                lines.append("【訓兵】馬廄空閒，可訓練騎兵（train_troops）")

            home_troops = state.get("troops", {}).get("home", {})
            if home_troops and "Rally Point" in buildings:
                lines.append(f"【軍事行動】有兵力 {home_troops}，可偵察或劫掠鄰近弱村")

            return "\n".join(lines)

        resources = state.get("resources", {})
        wood = resources.get("wood", 0)
        clay = resources.get("clay", 0)
        iron = resources.get("iron", 0)
        crop = resources.get("crop", 0)
        fields = state.get("resource_fields", {})
        empty_slots = state.get("empty_building_slots", [])

        lines = []

        field_options = []
        for ftype, flist in fields.items():
            for f in flist:
                level = f.get("level", 0)
                slot = f.get("slot", 0)
                if slot <= 0:
                    continue
                cost = knowledge_base.get_upgrade_cost(ftype, level)
                if cost and knowledge_base.can_afford_upgrade(ftype, level, resources):
                    total_cost = cost["wood"] + cost["clay"] + cost["iron"] + cost["crop"]
                    field_options.append(
                        (total_cost,
                         f"  - upgrade_resource_field: {ftype} slot#{slot} "
                         f"Lv{level}→{level+1} "
                         f"（費用: 木{cost['wood']} 土{cost['clay']} 鐵{cost['iron']} 糧{cost['crop']}）")
                    )
        field_options.sort(key=lambda x: x[0])  # 按總費用升序排列
        if field_options:
            lines.append(f"【資源田升級】共 {len(field_options)} 個可升級（按費用排序）：")
            lines.extend(option_text for _, option_text in field_options[:8])
            if len(field_options) > 8:
                lines.append(f"  ... 還有 {len(field_options)-8} 個")
        else:
            lines.append("【資源田升級】資源不足以升級任何資源田")

        building_options = []

        BUILDING_HINTS = {
            "Warehouse":     "擴充木材/黏土/鐵的儲量上限，快滿時必建",
            "Granary":       "擴充糧食儲量上限，快滿時必建",
            "Rally Point":   "必要建築，沒有它無法派兵出征",
            "Barracks":      "訓練步兵，軍事發展的第一步",
            "Main Building": "升級可加快所有建造速度",
            "Cranny":        "保護部分資源不被劫掠",
            "Hero's Mansion":"英雄裝備和冒險的基地",
            "Stable":        "訓練騎兵，中後期才需要",
            "Marketplace":   "和其他玩家交易資源",
            "Academy":       "解鎖進階兵種，中後期才需要",
            "Smithy":        "升級武器裝備，中後期才需要",
            "Sawmill":       "提升木材生產效率（需要 Main Building Lv5）",
            "Brickyard":     "提升黏土生產效率（需要 Main Building Lv5）",
            "Iron Foundry":  "提升鐵生產效率（需要 Main Building Lv5）",
            "Grain Mill":    "提升糧食生產效率（需要 Main Building Lv5）",
            "Town Hall":     "舉辦慶典，資源消耗極大",
            "Wall":          "提升防禦力，中後期才需要",
        }

        for bname, blevel in buildings.items():
            costs = BUILDING_COSTS.get(bname, {})
            cost = costs.get(blevel)
            if cost and (wood >= cost["wood"] and clay >= cost["clay"]
                         and iron >= cost["iron"] and crop >= cost["crop"]):
                hint = BUILDING_HINTS.get(bname, "")
                building_options.append(
                    f"  - upgrade_building: {bname} Lv{blevel}→{blevel+1} "
                    f"（費用: 木{cost['wood']} 土{cost['clay']} 鐵{cost['iron']} 糧{cost['crop']}）{' — ' + hint if hint else ''}"
                )

        if empty_slots:
            lines.append(f"\n【空建築格子】dorf2 有 {len(empty_slots)} 個空格可蓋新建築：")
            new_building_rec = knowledge_base.get_new_building_recommendation(state)
            if new_building_rec:
                rec = new_building_rec
                afford_tag = "✅ 資源足夠" if rec.get("can_afford") else "⚠️ 資源不足但值得規劃"
                lines.append(
                    f"【新建建築】推薦新建: {rec['building_name']} ({afford_tag})\n"
                    f"  原因: {rec['reason']}\n"
                    f"  → 使用 upgrade_building 並傳入 building_name='{rec['building_name']}', current_level=0"
                )
            for bname, level_costs in BUILDING_COSTS.items():
                if bname not in buildings:
                    cost = level_costs.get(0)
                    if cost and (wood >= cost["wood"] and clay >= cost["clay"]
                                 and iron >= cost["iron"] and crop >= cost["crop"]):
                        hint = BUILDING_HINTS.get(bname, "")
                        building_options.append(
                            f"  - upgrade_building: 新建 {bname} "
                            f"（費用: 木{cost['wood']} 土{cost['clay']} 鐵{cost['iron']} 糧{cost['crop']}）{' — ' + hint if hint else ''}"
                        )
            if not new_building_rec:
                lines.append("目前所有建築均已建造或暫無強烈推薦")
        else:
            lines.append("\n【建築建造】dorf2 無空格（所有槽位已佔用）")

        if building_options:
            lines.append("【建築建造/升級】可執行選項：")
            lines.extend(building_options)
        else:
            lines.append("【建築建造/升級】資源不足以建造任何建築")

        tq = state.get("troop_queue", [])
        if not tq:
            from shared.troop_data import get_troop
            barracks_level = buildings.get("Barracks", 0)
            stable_level = buildings.get("Stable", 0)
            if barracks_level:
                troop_lines = []
                for t in ["Phalanx", "Swordsman"]:
                    info = get_troop(t)
                    if info and info.attack > 0:
                        troop_lines.append(
                            f"  - {t}: atk={info.attack} def步={info.def_infantry} "
                            f"def騎={info.def_cavalry} 速={info.speed} 負重={info.carry} "
                            f"糧={info.crop_per_hour}/h"
                        )
                lines.append("\n【訓兵】兵舍空閒，可訓練步兵：")
                lines.extend(troop_lines)
            if stable_level:
                troop_lines = []
                for t in ["Theutates Thunder", "Druidrider", "Haeduan"]:
                    info = get_troop(t)
                    if info and info.attack > 0:
                        troop_lines.append(
                            f"  - {t}: atk={info.attack} def步={info.def_infantry} "
                            f"def騎={info.def_cavalry} 速={info.speed} 負重={info.carry} "
                            f"糧={info.crop_per_hour}/h"
                        )
                lines.append("\n【訓兵】馬廄空閒，可訓練騎兵：")
                lines.extend(troop_lines)

        home_troops = state.get("troops", {}).get("home", {})
        if home_troops and "Rally Point" in buildings:
            lines.append(f"\n【軍事行動】有兵力 {home_troops}，可偵察或劫掠鄰近弱村")

        wh_cap = resources.get("warehouse_cap", 800)
        gr_cap = resources.get("granary_cap", 800)
        warnings = []
        if wood > wh_cap * 0.8:
            warnings.append(f"木材快滿（{wood}/{wh_cap}）")
        if clay > wh_cap * 0.8:
            warnings.append(f"黏土快滿（{clay}/{wh_cap}）")
        if iron > wh_cap * 0.8:
            warnings.append(f"鐵快滿（{iron}/{wh_cap}）")
        if crop > gr_cap * 0.8:
            warnings.append(f"糧食快滿（{crop}/{gr_cap}）")
        if warnings:
            lines.append("\n【倉儲警告】" + " | ".join(warnings) + "（繼續生產資源會浪費！）")

        return "\n".join(lines)

    def _format_state(self, state: GameState) -> str:
        if not state:
            return "（無狀態資料）"
        parts = []
        res = state.get("resources", {})
        parts.append(
            f"資源: 木材={res.get('wood', 0)}/{res.get('warehouse_cap', '?')} "
            f"(+{res.get('wood_rate', 0)}/h), "
            f"黏土={res.get('clay', 0)}/{res.get('warehouse_cap', '?')} "
            f"(+{res.get('clay_rate', 0)}/h), "
            f"鐵={res.get('iron', 0)}/{res.get('warehouse_cap', '?')} "
            f"(+{res.get('iron_rate', 0)}/h), "
            f"糧食={res.get('crop', 0)}/{res.get('granary_cap', '?')} "
            f"(+{res.get('crop_rate', 0)}/h)"
        )

        buildings = state.get("buildings", {})
        bld_parts = ", ".join(f"{n}:Lv{l}" for n, l in sorted(buildings.items())[:15])
        parts.append(f"建築: {bld_parts}")

        empty_slots = state.get("empty_building_slots", [])
        parts.append(f"空建築格子: {len(empty_slots)} 個（可蓋新建築）")

        fields = state.get("resource_fields", {})
        total_fields = []
        for ftype, f_list in fields.items():
            for f in f_list:
                total_fields.append(f"{ftype}[{f['slot']}]:Lv{f['level']}")
        parts.append(f"資源田: {', '.join(total_fields[:12])}")

        bq = state.get("build_queue", [])
        if bq:
            parts.append(f"建造隊列: {bq[0].get('name', '?')} 剩 {bq[0].get('seconds_left', 0)} 秒")
        else:
            parts.append("建造隊列: 空閒")

        tq = state.get("troop_queue", [])
        if tq:
            parts.append(f"訓兵隊列: {tq[0].get('name', '?')} 剩 {tq[0].get('seconds_left', 0)} 秒")

        troops = state.get("troops", {}).get("home", {})
        if troops:
            parts.append(f"兵力: {', '.join(f'{n}x{c}' for n, c in troops.items())}")
        else:
            parts.append("兵力: 無")

        return "\n".join(parts)

    def _format_actions(self, actions: list) -> str:
        if not actions:
            return "（無）"
        lines = []
        for a in actions:
            ts = a.get("timestamp", "")[5:19]
            act = a.get("action_type", "")
            success = "✅" if a.get("success") else "❌"
            result = a.get("result_text", "")[:60]
            lines.append(f"{ts} {success} {act}: {result}")
        return "\n".join(lines)

    async def think_and_act(self, state: GameState, context: dict) -> list[dict]:
        try:
            bq = state.get("build_queue", [])
            if not bq:
                queue_status = "建造隊列空閒，可以建造/升級一項"
            else:
                queue_status = f"建造隊列有 {len(bq)} 項，剩 {bq[0].get('seconds_left',0)} 秒完成。本輪跳過建造動作。"

            state_str = self._format_state(state)
            available_actions = self._build_available_actions(state)
            recent_actions = self._format_actions(context.get("recent_actions", []))
            memory_summary = context.get("memory", "（無）")
            strategy_notes = context.get("strategy_notes", "（無）")
            nudge = context.get("nudge", "")
            map_intel = context.get("map_intel", "（尚未掃描地圖）")

            hero = state.get("hero", {})
            if hero.get("hero_health") is not None:
                hero_lines = []
                hero_lines.append(f"英雄血量: {hero['hero_health']}%，等級: {hero.get('hero_level', '?')}，狀態: {hero.get('hero_status', '?')}")
                if hero.get("hero_resource_rewards") and any(v > 0 for v in hero["hero_resource_rewards"].values()):
                    rr = hero["hero_resource_rewards"]
                    hero_lines.append(f"【⚠️ 待領取資源獎勵】木{rr.get('wood',0)} 土{rr.get('clay',0)} 鐵{rr.get('iron',0)} 糧{rr.get('crop',0)} → 請立即執行 collect_hero_resources")
                if hero.get("hero_available_points", 0) > 0:
                    hero_lines.append(f"【可分配屬性點】{hero['hero_available_points']} 點待分配 → 可執行 allocate_hero_points")
                if hero.get("hero_status") == "idle" and hero.get("hero_adventures"):
                    adv = hero["hero_adventures"]
                    easy = [a for a in adv if a.get("difficulty") == "easy"]
                    if easy:
                        hero_lines.append(f"【可出征冒險】有 {len(easy)} 個簡單冒險，ID: {easy[0]['id']}，時長 {easy[0].get('duration_minutes','?')} 分鐘")
                hero_status_text = "\n".join(hero_lines)
            else:
                hero_status_text = "（英雄資料暫不可用）"

            quests = state.get("quests", {})
            quest_lines = []
            ready = quests.get("total_reward_ready", 0)
            if ready > 0:
                quest_lines.append(f"【⚠️ 有 {ready} 個任務獎勵可領取】→ 請優先執行 collect_quest_reward（免費資源，不應錯過）")
            daily = quests.get("daily_quests", [])
            for q in daily:
                if q.get("reward_ready"):
                    quest_lines.append(f"  - 每日任務「{q['title']}」已完成，可領獎")
                elif not q.get("completed"):
                    quest_lines.append(f"  - 每日任務「{q['title']}」進行中：{q.get('progress', '')}")
            main_q = quests.get("main_quests", [])
            for q in main_q[:3]:
                if q.get("reward_ready"):
                    quest_lines.append(f"  - 主線任務「{q['title']}」已完成，可領獎")
            quest_status_text = "\n".join(quest_lines) if quest_lines else "（無待處理任務）"

            dipl = state.get("diplomatic_intel", {})
            if dipl:
                dipl_lines = [dipl.get("summary_text", "（無地圖情報）")]
                if dipl.get("new_player_protection"):
                    hours = dipl.get("protection_hours_remaining", 0)
                    dipl_lines.append(f"\n⛨ 保護期剩餘 {hours:.0f} 小時 — 本輪禁止任何軍事行動")
                else:
                    raid_targets = dipl.get("raid_targets", [])
                    if raid_targets:
                        rt = raid_targets[0]
                        dipl_lines.append(f"\n🎯 推薦劫掠: ({rt['x']}|{rt['y']}) 無主村，距離 {rt['distance']} 格")
                    threats = dipl.get("threats", [])
                    if threats:
                        for t in threats[:2]:
                            dipl_lines.append(f"⚠️ 威脅警示: {t['player_name']} 人口 {t['population']}，距 {t['distance']} 格")
                    scout_pri = dipl.get("scout_priority", [])
                    if scout_pri:
                        s = scout_pri[0]
                        dipl_lines.append(f"🔍 偵察建議: ({s['x']}|{s['y']}) — {s.get('reason','')}")
                diplomatic_intel_text = "\n".join(dipl_lines)
            else:
                diplomatic_intel_text = "（地圖尚未掃描，請等待下次自動掃描）"

            system_prompt = AUTONOMOUS_SYSTEM_PROMPT.format(
                state=state_str,
                available_actions=available_actions,
                queue_status=queue_status,
                hero_status=hero_status_text,
                quest_status=quest_status_text,
                diplomatic_intel=diplomatic_intel_text,
                map_intel=map_intel,
                recent_actions=recent_actions,
                memory=memory_summary,
                strategy_notes=strategy_notes,
                nudge=nudge,
            )

            logger.info("📡 全自主決策呼叫 LLM...")
            actions = await llm_client.decide_multi(system_prompt)
            logger.info(f"✅ LLM 回傳 {len(actions)} 個動作: {[a['name'] for a in actions]}")
            return actions

        except Exception as e:
            logger.error(f"全自主決策失敗: {e}")
            return []


decision_maker = AutonomousBrain()