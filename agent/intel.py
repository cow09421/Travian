import json
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from scraper.browser import browser_manager, Page
from parser.map_scanner import scan_map_with_js
from config import config
from database import db
from parser.state_builder import GameState

MAP_SCAN_INTERVAL = 600


class IntelManager:

    def __init__(self):
        self._last_scan_time: Optional[datetime] = None
        self._home_x: int = 0
        self._home_y: int = 0
        self._village_name: str = ""
        self._scan_radius: int = 20

    def should_scan_map(self) -> bool:
        if self._last_scan_time is None:
            return True
        elapsed = (datetime.now(timezone.utc) - self._last_scan_time).total_seconds()
        return elapsed >= MAP_SCAN_INTERVAL

    def set_home(self, x: int, y: int, name: str = ""):
        if x and y:
            self._home_x = int(x)
            self._home_y = int(y)
        if name:
            self._village_name = name

    async def extract_coords_from_page(self, page) -> tuple[int, int]:
        try:
            coords_json = await page.evaluate("""
                (() => {
                    const candidates = [
                        window.globalVillage,
                        window.villageData,
                        window.activeVillage,
                        window.mapPosition,
                        window.Travian && window.Travian.village,
                        window.Game && window.Game.village,
                    ];
                    for (const c of candidates) {
                        if (c && typeof c.x === 'number' && typeof c.y === 'number') {
                            return JSON.stringify({x: c.x, y: c.y, source: 'global_var'});
                        }
                    }

                    const coordEl = document.querySelector(
                        '[data-x][data-y], #villageCoords, .coords, .mapCoordinates'
                    );
                    if (coordEl) {
                        const x = parseInt(coordEl.getAttribute('data-x') || coordEl.textContent);
                        const y = parseInt(coordEl.getAttribute('data-y') || '');
                        if (!isNaN(x) && !isNaN(y)) {
                            return JSON.stringify({x, y, source: 'dom_attr'});
                        }
                    }

                    const karteLinks = document.querySelectorAll('a[href*="karte.php?x="]');
                    for (const link of karteLinks) {
                        const href = link.getAttribute('href') || '';
                        const m = href.match(/karte\\.php\\?x=(-?\\d+)&(?:amp;)?y=(-?\\d+)/);
                        if (m) {
                            return JSON.stringify({x: parseInt(m[1]), y: parseInt(m[2]), source: 'karte_link'});
                        }
                    }

                    const scripts = document.querySelectorAll('script');
                    for (const s of scripts) {
                        const m = s.textContent.match(/[{,\\s]x\\s*:\\s*(-?\\d+)[^}]*y\\s*:\\s*(-?\\d+)/);
                        if (m) {
                            const x = parseInt(m[1]), y = parseInt(m[2]);
                            if (x >= -400 && x <= 400 && y >= -400 && y <= 400) {
                                return JSON.stringify({x, y, source: 'script_scan'});
                            }
                        }
                    }

                    return JSON.stringify({x: 0, y: 0, source: 'not_found'});
                })()
            """)

            data = json.loads(coords_json)
            x, y = data.get("x", 0), data.get("y", 0)
            source = data.get("source", "?")

            if x or y:
                logger.info(f"📍 從頁面取得村莊座標: ({x}|{y}) via {source}")
                self.set_home(x, y)
                return x, y

        except Exception as e:
            logger.warning(f"從頁面取得座標失敗: {e}")

        return 0, 0

    async def scan_nearby(self, page: Page) -> dict:
        if not self._home_x and not self._home_y:
            logger.warning("尚未設定主村座標，跳過地圖掃描")
            return {}

        logger.info(f"🗺️ 掃描地圖，中心: ({self._home_x}|{self._home_y})，半徑: {self._scan_radius}")

        villages = await self._scan_via_statistics(page)

        if not villages:
            logger.info("統計頁面失敗，嘗試從戰報取得村莊資料...")
            villages = await self._scan_via_reports(page)

        if not villages:
            logger.info("嘗試 karte.php 深度掃描...")
            villages = await self._scan_via_karte_deep(page)

        saved_count = 0
        for village in villages:
            vx = village.get("x", 0)
            vy = village.get("y", 0)
            if vx == self._home_x and vy == self._home_y:
                continue
            try:
                await db.save_map_intel({
                    "coord_x": vx,
                    "coord_y": vy,
                    "player_name": village.get("player_name", ""),
                    "village_name": village.get("name", ""),
                    "population": village.get("population", 0),
                    "distance": abs(vx - self._home_x) + abs(vy - self._home_y),
                })
                saved_count += 1
            except Exception as e:
                logger.debug(f"儲存村莊資料失敗: {e}")

        self._last_scan_time = datetime.now(timezone.utc)
        logger.info(f"地圖掃描完成，發現 {len(villages)} 個村莊，儲存 {saved_count} 筆")

        if len(villages) < 5 and self._scan_radius < 50 and villages:
            self._scan_radius += 5
            logger.info(f"村莊太少，下次擴大掃描半徑至 {self._scan_radius}")
        elif not villages:
            logger.info("完全沒掃到村莊（可能頁面結構不符），暫不擴大掃描半徑")

        return {"villages": villages}

    async def _scan_via_statistics(self, page) -> list:
        import re
        from bs4 import BeautifulSoup

        villages = []
        try:
            for page_num in range(1, 4):
                stats_url = f"{config.travian_url}/statistics/village?page={page_num}"
                ok = await browser_manager.safe_goto(page, stats_url)
                if not ok:
                    break

                html = await page.content()
                soup = BeautifulSoup(html, "lxml")

                found_on_page = 0

                for row in soup.find_all('tr'):
                    name_cell = row.select_one('td.villageName a')
                    coord_cell = row.select_one('td.coords a')

                    if not coord_cell:
                        continue

                    href = coord_cell.get('href', '')
                    m_karte = re.search(r'karte\.php\?x=(-?\d+)&(?:amp;)?y=(-?\d+)', href)
                    if not m_karte:
                        continue

                    x, y = int(m_karte.group(1)), int(m_karte.group(2))
                    if abs(x) > 400 or abs(y) > 400:
                        continue

                    name = ""
                    if name_cell:
                        name = name_cell.get_text(strip=True)

                    cells = row.find_all('td')
                    player_name = ""
                    population = 0
                    if len(cells) >= 3:
                        pc = cells[2]
                        if pc:
                            player_name = pc.get_text(strip=True)
                    if len(cells) >= 4:
                        try:
                            population = int(re.sub(r'[^\d]', '', cells[3].get_text(strip=True)))
                        except (ValueError, TypeError):
                            pass

                    villages.append({
                        "x": x, "y": y,
                        "name": name or f"村莊({x}|{y})",
                        "population": population,
                        "player_name": player_name,
                        "distance": abs(x - self._home_x) + abs(y - self._home_y),
                    })
                    found_on_page += 1

                logger.info(f"統計頁面第{page_num}頁掃描到 {found_on_page} 個村莊")
                if found_on_page == 0:
                    break

            seen = set()
            unique = []
            for v in villages:
                k = f"{v['x']}|{v['y']}"
                if k not in seen:
                    seen.add(k)
                    unique.append(v)

            logger.info(f"統計頁面共掃描到 {len(unique)} 個村莊")
            return unique

        except Exception as e:
            logger.error(f"統計頁面掃描失敗: {e}")
            return []

    async def _scan_via_karte_deep(self, page) -> list:
        import json
        villages = []
        all_responses = []

        async def capture_response(response):
            try:
                url = response.url
                ct = response.headers.get('content-type', '')
                if 'json' in ct or 'javascript' in ct.lower():
                    try:
                        body = await response.text()
                        if any(kw in body for kw in ['village', 'coord', '"x"', '"y"', 'population']):
                            all_responses.append((url, body))
                    except Exception:
                        pass
            except Exception:
                pass

        page.on('response', capture_response)

        map_url = f"{config.travian_url}/karte.php?x={self._home_x}&y={self._home_y}"
        ok = await browser_manager.safe_goto(page, map_url)

        try:
            await page.wait_for_selector('canvas', timeout=15000)
            logger.info("canvas 已出現，等待地圖資料載入...")
            canvas = page.locator('canvas').first
            bbox = await canvas.bounding_box()
            if bbox:
                cx = bbox['x'] + bbox['width'] / 2
                cy = bbox['y'] + bbox['height'] / 2
                await page.mouse.move(cx, cy)
                await page.mouse.wheel(0, 100)
                await page.mouse.wheel(0, -100)
        except Exception as e:
            logger.warning(f"等待 canvas 失敗: {e}")

        await page.wait_for_timeout(8000)
        page.remove_listener('response', capture_response)

        try:
            js_data = await page.evaluate("""
            (() => {
                const results = [];
                const sources = [
                    window.TravianMap, window.mapData, window.villageData,
                    window.Travian && window.Travian.map,
                    window.Travian && window.Travian.Map && window.Travian.Map.data,
                ];
                for (const s of sources) {
                    if (s && typeof s === 'object') {
                        results.push(JSON.stringify(s));
                    }
                }
                return results;
            })()
            """)
            for item in js_data:
                try:
                    data = json.loads(item)
                    if isinstance(data, list):
                        for v in data:
                            if isinstance(v, dict) and 'x' in v and 'y' in v:
                                x, y = int(v['x']), int(v['y'])
                                if abs(x) <= 400 and abs(y) <= 400:
                                    villages.append({
                                        "x": x, "y": y,
                                        "name": v.get('name', f"({x}|{y})"),
                                        "population": int(v.get('population', 0)),
                                        "player_name": v.get('playerName', ''),
                                        "distance": abs(x - self._home_x) + abs(y - self._home_y),
                                    })
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"從 window 取地圖資料失敗: {e}")

        for url, body in all_responses:
            try:
                data = json.loads(body)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and 'x' in item and 'y' in item:
                            x, y = int(item['x']), int(item['y'])
                            if abs(x) <= 400 and abs(y) <= 400:
                                villages.append({
                                    "x": x, "y": y,
                                    "name": item.get('name', f"({x}|{y})"),
                                    "population": int(item.get('population', 0)),
                                    "player_name": item.get('playerName', ''),
                                    "distance": abs(x - self._home_x) + abs(y - self._home_y),
                                })
            except Exception:
                pass

        logger.info(f"karte.php 深度掃描到 {len(villages)} 個村莊")
        return villages

    async def _scan_via_reports(self, page) -> list:
        from scraper.browser import browser_manager
        from config import config
        import re
        from bs4 import BeautifulSoup

        villages = []
        try:
            reports_url = f"{config.travian_url}/report/overview"
            ok = await browser_manager.safe_goto(page, reports_url)
            if not ok:
                return []

            html = await page.content()
            soup = BeautifulSoup(html, "lxml")

            coord_pattern = re.compile(r'\((-?\d{1,4})\|(-?\d{1,4})\)')
            for link in soup.find_all('a', href=True):
                title = link.get('title', '') or link.get_text(strip=True)
                m = coord_pattern.search(title)
                if m:
                    x, y = int(m.group(1)), int(m.group(2))
                    if abs(x) <= 400 and abs(y) <= 400:
                        villages.append({
                            "x": x, "y": y,
                            "name": title.split('(')[0].strip() or f"村莊({x}|{y})",
                            "population": 0,
                            "player_name": "",
                            "distance": abs(x - self._home_x) + abs(y - self._home_y),
                        })

            seen = set()
            unique = []
            for v in villages:
                k = f"{v['x']}|{v['y']}"
                if k not in seen:
                    seen.add(k)
                    unique.append(v)

            logger.info(f"戰報掃描到 {len(unique)} 個村莊")
            return unique
        except Exception as e:
            logger.error(f"戰報掃描失敗: {e}")
            return []

    async def get_raid_targets(self) -> list[dict]:
        villages = await db.get_map_intel(limit=100)
        targets = []
        for v in villages:
            pop = v.get("population", 99999)
            dist = v.get("distance", 999)
            if pop < 500 and 0 < dist <= 15:
                targets.append(v)
        targets.sort(key=lambda x: (x.get("distance", 999), x.get("population", 999)))
        return targets[:10]

    async def get_nearby_overview(self) -> list[dict]:
        return await db.get_map_intel(limit=30)

    async def assess_threat_level(self) -> str:
        villages = await db.get_map_intel(limit=100)
        nearby_strong = [v for v in villages
                         if v.get("population", 0) > 2000 and v.get("distance", 999) < 7]
        if nearby_strong:
            return "danger"
        nearby_medium = [v for v in villages
                         if v.get("population", 0) > 1000 and v.get("distance", 999) < 10]
        if nearby_medium:
            return "warning"
        return "safe"

    async def get_diplomatic_intel(self, state: GameState) -> dict:
        villages = await db.get_map_intel(limit=200)
        home_x = self._home_x
        home_y = self._home_y

        protection_hours = state.get("resources", {}).get("protection_hours_remaining", 0)
        in_protection = protection_hours > 0

        raid_targets = []
        threats = []
        neutrals = []
        scout_priority = []

        for v in villages:
            vx = v.get("coord_x", 0)
            vy = v.get("coord_y", 0)
            if not vx and not vy:
                continue
            dist = abs(vx - home_x) + abs(vy - home_y)
            population = v.get("population", 0)
            player = v.get("player_name", "") or ""
            ally = v.get("ally_name", "") or ""
            village_name = v.get("village_name", "")

            if not player.strip():
                raid_targets.append({
                    "x": vx, "y": vy,
                    "village_name": village_name,
                    "player_name": "",
                    "population": population,
                    "distance": dist,
                    "threat_level": "none",
                    "last_scouted": None,
                    "estimated_resources": "low",
                })
            elif population < 100 and dist <= 15:
                scout_priority.append({
                    "x": vx, "y": vy,
                    "village_name": village_name,
                    "player_name": player,
                    "population": population,
                    "distance": dist,
                    "reason": f"低人口村 ({population})，可能是好劫掠目標",
                })
            elif population > 500 and dist <= 10:
                threat_level = "high" if (population > 1000 or dist <= 5) else "medium"
                threats.append({
                    "x": vx, "y": vy,
                    "village_name": village_name,
                    "player_name": player,
                    "population": population,
                    "distance": dist,
                    "threat_level": threat_level,
                    "ally": ally,
                    "note": f"人口{population}、距離{dist}格" + ("，潛在威脅" if threat_level == "high" else ""),
                })
            else:
                neutrals.append({
                    "x": vx, "y": vy,
                    "village_name": village_name,
                    "player_name": player,
                    "population": population,
                    "distance": dist,
                })

        raid_targets.sort(key=lambda x: x["distance"])
        threats.sort(key=lambda x: x["distance"])
        scout_priority.sort(key=lambda x: x["distance"])

        lines = []
        if in_protection:
            lines.append(f"⛨ 新手保護期還有 {protection_hours:.0f} 小時，無法攻擊/被攻擊")
        if raid_targets:
            rt = raid_targets[0]
            lines.append(f"🎯 最佳劫掠目標: ({rt['x']}|{rt['y']}) {rt.get('village_name','')} 距離{rt['distance']}格，無主村")
        if threats:
            t = threats[0]
            lines.append(f"⚠️ 最近威脅: ({t['x']}|{t['y']}) 玩家{t['player_name']} 人口{t['population']} 距離{t['distance']}格")
        if scout_priority:
            s = scout_priority[0]
            lines.append(f"🔍 建議偵察: ({s['x']}|{s['y']}) {s.get('reason','')}")
        if not raid_targets and not threats:
            lines.append("周圍環境安全，無緊急外交行動需求")

        return {
            "raid_targets": raid_targets[:5],
            "threats": threats[:3],
            "neutrals": neutrals[:5],
            "scout_priority": scout_priority[:3],
            "summary_text": "\n".join(lines),
            "new_player_protection": in_protection,
            "protection_hours_remaining": protection_hours,
        }

    async def build_summary(self) -> str:
        threat = await self.assess_threat_level()
        targets = await self.get_raid_targets()
        nearby = await self.get_nearby_overview()

        lines = []

        if not nearby:
            lines.append("地圖情報：尚未掃描到任何附近村莊")
            lines.append(f"（主村座標: ({self._home_x}|{self._home_y})，下輪將掃描地圖）")
        else:
            lines.append(f"威脅等級: {threat} | 附近已知村莊: {len(nearby)} 個")

            if targets:
                lines.append(f"\n可劫掠目標（人口<500，距離≤15格）：{len(targets)} 個")
                for t in targets[:5]:
                    lines.append(
                        f"  ({t.get('coord_x')}|{t.get('coord_y')}) "
                        f"{t.get('village_name','?')} "
                        f"人口={t.get('population',0)} "
                        f"距離={t.get('distance','?')}"
                    )
            else:
                lines.append("目前無適合劫掠目標（或尚未掃描到）")

            close_ones = [v for v in nearby if v.get("distance", 999) <= 10][:5]
            if close_ones:
                lines.append(f"\n10格內鄰村：")
                for v in close_ones:
                    lines.append(
                        f"  ({v.get('coord_x')}|{v.get('coord_y')}) "
                        f"{v.get('village_name','?')} "
                        f"人口={v.get('population',0)}"
                    )

        last = "從未" if not self._last_scan_time else self._last_scan_time.strftime("%H:%M")
        lines.append(f"\n上次掃描: {last}")

        return "\n".join(lines)


intel_manager = IntelManager()