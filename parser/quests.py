import re
from bs4 import BeautifulSoup
from loguru import logger


def parse_quests(page_or_html) -> dict:
    result = {
        "daily_quests": [],
        "main_quests": [],
        "total_reward_ready": 0,
    }

    try:
        if hasattr(page_or_html, "content"):
            html = page_or_html.content()
        else:
            html = page_or_html

        if not html:
            return result

        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text()

        quest_containers = [
            soup.select_one(".dailyQuests, .daily-quests, #dailyQuests, [class*='dailyQuest']"),
            soup.select_one(".mainQuests, .main-quests, #mainQuests, [class*='mainQuest']"),
            soup.select_one(".questMaster, #questMaster, .questmaster, [class*='quest']"),
        ]

        if not any(quest_containers):
            quest_containers = [soup]

        daily_reward_ready = 0
        main_reward_ready = 0

        raw_daily = []
        raw_main = []

        for container in quest_containers:
            if container is None:
                continue
            container_html = str(container)

            for quest_el in container.select(".questItem, .quest, .questCard, [class*='quest']"):
                qid = quest_el.get("data-id", "") or quest_el.get("id", "")
                title_el = quest_el.select_one(".title, .questTitle, .questName")
                title = title_el.get_text(strip=True) if title_el else quest_el.get_text(strip=True)[:60]

                is_completed = bool(quest_el.select_one(".completed, .done, .finished"))
                has_reward = bool(quest_el.select_one(".collectReward, .rewardReady, .reward-available"))
                progress_el = quest_el.select_one(".progress, .questProgress")
                progress = progress_el.get_text(strip=True) if progress_el else ""

                reward = {}
                reward_text = quest_el.get_text()
                for res_name, kw in [("wood", "wood"), ("clay", "clay"), ("iron", "iron"), ("crop", "crop"), ("silver", "silver")]:
                    m = re.search(rf'{kw}[:\s]*(\d+)', reward_text, re.I)
                    if m:
                        reward[res_name] = int(m.group(1))

                is_daily = "daily" in (title.lower() + (quest_el.get("class", "") or ""))
                item = {
                    "id": qid or title,
                    "title": title,
                    "completed": is_completed,
                    "reward_ready": has_reward,
                    "reward": reward,
                    "progress": progress,
                }

                if is_daily:
                    raw_daily.append(item)
                    if has_reward:
                        daily_reward_ready += 1
                else:
                    raw_main.append(item)
                    if has_reward:
                        main_reward_ready += 1

        if not raw_daily and not raw_main:
            for line in text.split("\n")[:50]:
                line = line.strip()
                if not line:
                    continue
                m = re.search(r'(?:Collect|領取|收穫|完成).{0,20}(?:\d+\s*wood|\d+\s*clay|\d+\s*iron|\d+\s*crop|\d+\s*silver)', line, re.I)
                if m:
                    daily_reward_ready += 1

        result["daily_quests"] = raw_daily
        result["main_quests"] = raw_main
        result["total_reward_ready"] = daily_reward_ready + main_reward_ready

    except Exception as e:
        logger.warning(f"任務頁面解析失敗: {e}")

    return result