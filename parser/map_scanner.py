import re
import json
import os
from typing import Optional
from bs4 import BeautifulSoup
from loguru import logger


async def scan_map_with_js(page, center_x: int, center_y: int, radius: int = 15) -> dict:
    from scraper.browser import browser_manager
    from config import config

    all_villages = []
    seen_keys = set()
    all_responses = []

    async def capture_response(response):
        try:
            url = response.url
            status = response.status
            ct = response.headers.get('content-type', '')
            try:
                body = await response.text()
            except Exception:
                body = '[binary or unreadable]'
            all_responses.append((url, status, ct, body))
        except Exception as e:
            all_responses.append((str(e), 0, '', ''))

    page.on('response', capture_response)

    map_url = f"{config.travian_url}/karte.php?x={center_x}&y={center_y}&zoom=2"
    ok = await browser_manager.safe_goto(page, map_url)
    await page.wait_for_timeout(4000)

    page.remove_listener('response', capture_response)

    html_content = ""
    if ok:
        try:
            html_content = await page.content()
        except Exception as e:
            logger.error(f"取得頁面內容失敗: {e}")

    try:
        debug_path = os.path.join(os.path.dirname(__file__), '..', 'debug_map_dump.txt')
        with open(debug_path, 'w', encoding='utf-8') as f:
            f.write(f"=== MAP SCAN DEBUG ===\n")
            f.write(f"Target URL: {map_url}\n")
            f.write(f"Navigation OK: {ok}\n")
            f.write(f"Total responses: {len(all_responses)}\n\n")
            for url, status, ct, body in all_responses:
                f.write(f"[{status}] {str(ct)[:40]:<40} {url[:120]}\n")
                if body and body != '[binary or unreadable]':
                    f.write(f"  BODY: {str(body)[:300]}\n")
            f.write(f"\n=== PAGE HTML (first 5000 chars) ===\n{html_content[:5000]}\n")
        logger.info(f"診斷資料已寫入: {debug_path}")
    except Exception as e:
        logger.error(f"寫入診斷檔案失敗: {e}")

    # 步驟 1：從攔截到的 API JSON 回應中解析
    for url, status, ct, body in all_responses:
        if status != 200:
            continue
        if 'json' in str(ct) or 'javascript' in str(ct):
            try:
                data = json.loads(body)
                extracted = _extract_villages_from_api_response(data, center_x, center_y)
                for v in extracted:
                    key = f"{v['x']}|{v['y']}"
                    if key not in seen_keys:
                        seen_keys.add(key)
                        all_villages.append(v)
            except Exception:
                pass
    logger.info(f"從 API 回應解析到 {len(all_villages)} 個村莊")

    # 步驟 2：從 script 標籤解析
    if not all_villages and html_content:
        script_villages = _extract_villages_from_scripts(html_content, center_x, center_y)
        for v in script_villages:
            key = f"{v['x']}|{v['y']}"
            if key not in seen_keys:
                seen_keys.add(key)
                all_villages.append(v)
        logger.info(f"從 script 標籤解析到 {len(all_villages)} 個村莊")

    # 步驟 3：從 HTML area/a 標籤解析
    if not all_villages and html_content:
        html_villages = _parse_karte_html(html_content, center_x, center_y)
        for v in html_villages:
            key = f"{v['x']}|{v['y']}"
            if key not in seen_keys:
                seen_keys.add(key)
                all_villages.append(v)
        logger.info(f"從 HTML area/a 標籤解析到 {len(all_villages)} 個村莊")

    # 步驟 4：從 window JS 變數取得地圖資料
    if not all_villages:
        try:
            js_result = await page.evaluate("""
            (() => {
                const candidates = [
                    window.TravianMap,
                    window.mapData,
                    window.villageList,
                    window.villages,
                    window.Travian && window.Travian.map,
                    window.Travian && window.Travian.mapData,
                ];
                for (const c of candidates) {
                    if (c) return JSON.stringify(c);
                }
                const mapEl = document.querySelector('[data-villages], #mapContainer, .mapContainer');
                if (mapEl) {
                    const dv = mapEl.getAttribute('data-villages');
                    if (dv) return dv;
                }
                return null;
            })()
            """)
            if js_result:
                try:
                    data = json.loads(js_result)
                    extracted = _extract_villages_from_api_response(data, center_x, center_y)
                    for v in extracted:
                        key = f"{v['x']}|{v['y']}"
                        if key not in seen_keys:
                            seen_keys.add(key)
                            all_villages.append(v)
                    logger.info(f"從 window JS 變數解析到 {len(all_villages)} 個村莊")
                except Exception as e:
                    logger.debug(f"JS 變數 JSON 解析失敗: {e}")
        except Exception as e:
            logger.warning(f"執行 JS 取地圖資料失敗: {e}")

    # 步驟 5：回退到通用 HTML 解析
    if not all_villages and html_content:
        fallback = _fallback_html_parse(html_content, center_x, center_y)
        all_villages = fallback.get("villages", [])
        logger.info(f"從 HTML 回退解析到 {len(all_villages)} 個村莊")

    # 過濾掉主村
    all_villages = [v for v in all_villages if not (v['x'] == center_x and v['y'] == center_y)]

    logger.info(f"地圖掃描完成，共發現 {len(all_villages)} 個村莊")
    return {"villages": all_villages, "current_x": center_x, "current_y": center_y}


def _extract_villages_from_scripts(html: str, center_x: int, center_y: int) -> list:
    villages = []
    seen = set()

    patterns = [
        r'Travian\.Game\.Map\.init\((\{.+?\})\)',
        r'mapData\s*=\s*(\{.+?\})\s*;',
        r'(?:mapData|tileData|villageData|mapInit)\s*=\s*(\{[^;]+\})',
        r'"villages"\s*:\s*(\[(?:[^[\]]*|\[(?:[^[\]]*|\[[^\]]*\])*\])*\])',
        r'var\s+(?:map|village)s?\s*=\s*(\[(?:[^[\]]*|\[(?:[^[\]]*|\[[^\]]*\])*\])*\])',
    ]

    for pattern in patterns:
        matches = re.findall(pattern, html, re.DOTALL)
        for match in matches:
            try:
                data = json.loads(match)
                extracted = _extract_villages_from_api_response(data, center_x, center_y)
                for v in extracted:
                    key = f"{v['x']}|{v['y']}"
                    if key not in seen:
                        seen.add(key)
                        villages.append(v)
                if extracted:
                    return villages
            except Exception:
                pass

    return villages


def _parse_karte_html(html: str, center_x: int, center_y: int) -> list:
    villages = []
    seen = set()

    soup = BeautifulSoup(html, "lxml")

    coord_from_href = re.compile(r'karte\.php\?x=(-?\d+)&(?:amp;)?y=(-?\d+)')
    village_title = re.compile(r'^(.+?)\s*\((-?\d+)\|(-?\d+)\)')

    for area in soup.find_all('area'):
        href = area.get('href', '')
        title = area.get('title', '')
        alt = area.get('alt', '')

        m_href = coord_from_href.search(href)
        m_title = village_title.search(title) or village_title.search(alt)

        if m_href:
            x, y = int(m_href.group(1)), int(m_href.group(2))
            name = ""
            if m_title:
                name = m_title.group(1).strip()
            key = f"{x}|{y}"
            if key not in seen and (abs(x) <= 400 and abs(y) <= 400):
                seen.add(key)
                villages.append({
                    "x": x, "y": y,
                    "name": name or f"村莊({x}|{y})",
                    "population": 0,
                    "player_name": "",
                })

    for a in soup.find_all('a', href=True):
        href = a.get('href', '')
        m = coord_from_href.search(href)
        if m:
            x, y = int(m.group(1)), int(m.group(2))
            key = f"{x}|{y}"
            if key not in seen and (abs(x) <= 400 and abs(y) <= 400):
                seen.add(key)
                villages.append({
                    "x": x, "y": y,
                    "name": a.get_text(strip=True) or f"村莊({x}|{y})",
                    "population": 0,
                    "player_name": "",
                })

    return villages


def _extract_villages_from_api_response(data, center_x: int, center_y: int) -> list:
    villages = []

    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                v = _try_parse_village_item(item)
                if v:
                    villages.append(v)

    elif isinstance(data, dict):
        for key in ['villages', 'data', 'cells', 'tiles', 'result', 'items']:
            if key in data and isinstance(data[key], list):
                for item in data[key]:
                    v = _try_parse_village_item(item)
                    if v:
                        villages.append(v)
                if villages:
                    break

        if not villages:
            for x_key, row in data.items():
                if isinstance(row, dict):
                    for y_key, tile in row.items():
                        try:
                            x, y = int(x_key), int(y_key)
                            if isinstance(tile, dict) and (tile.get('name') or tile.get('villageName')):
                                villages.append({
                                    "x": x, "y": y,
                                    "name": tile.get('name') or tile.get('villageName', f'村莊({x}|{y})'),
                                    "population": int(tile.get('population', 0)),
                                    "player_name": tile.get('playerName', ''),
                                })
                        except (ValueError, TypeError):
                            pass

    return villages


def _try_parse_village_item(item: dict) -> Optional[dict]:
    x = item.get('x') or item.get('coordX') or item.get('mapX')
    y = item.get('y') or item.get('coordY') or item.get('mapY')

    if x is None or y is None:
        return None

    try:
        x, y = int(x), int(y)
        if abs(x) > 400 or abs(y) > 400:
            return None

        name = (item.get('name') or item.get('villageName') or
                item.get('village_name') or f'村莊({x}|{y})')
        population = int(item.get('population', item.get('pop', 0)))
        player = item.get('playerName', item.get('player_name', ''))

        return {"x": x, "y": y, "name": name, "population": population, "player_name": player}
    except (ValueError, TypeError):
        return None


def _fallback_html_parse(html: str, center_x: int, center_y: int) -> dict:
    result = {"villages": [], "current_x": center_x, "current_y": center_y}
    try:
        soup = BeautifulSoup(html, "lxml")
        seen = set()

        coord_pattern = re.compile(r'\(?(-?\d{1,4})\s*[|｜]\s*(-?\d{1,4})\)?')
        for el in soup.find_all(["a", "td", "div", "span", "area"], limit=500):
            text = el.get_text(" ", strip=True)
            href = el.get("href", "")
            title = el.get("title", "")
            for match in coord_pattern.finditer(f"{text} {href} {title}"):
                x, y = int(match.group(1)), int(match.group(2))
                if abs(x) > 400 or abs(y) > 400:
                    continue
                key = f"{x}|{y}"
                if key not in seen:
                    seen.add(key)
                    result["villages"].append({
                        "x": x, "y": y,
                        "name": f"村莊({x}|{y})",
                        "population": 0,
                        "player_name": "",
                        "distance": abs(x - center_x) + abs(y - center_y),
                    })
    except Exception as e:
        logger.error(f"HTML 回退解析失敗: {e}")
    return result


def parse_map(html: str) -> dict:
    return _fallback_html_parse(html, 0, 0)