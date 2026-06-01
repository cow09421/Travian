"""
診斷腳本：抓取 Barracks 頁面 + statistiken.php 的 HTML 和截圖
用法: python debug_inspect.py
輸出: debug_barracks.html, debug_barracks.png, debug_stats.html, debug_stats.png
"""
import asyncio
import os
from playwright.async_api import async_playwright
from dotenv import load_dotenv

load_dotenv()

TRAVIAN_URL = os.getenv("TRAVIAN_URL", "").rstrip("/")
USERNAME = os.getenv("TRAVIAN_USERNAME", "")
PASSWORD = os.getenv("TRAVIAN_PASSWORD", "")


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=50)
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = await ctx.new_page()

        # 登入流程
        await page.goto(f"{TRAVIAN_URL}/dorf1.php", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        # 嘗試載入 session 檔案
        session_file = "session.json"
        if os.path.exists(session_file):
            try:
                import json
                with open(session_file) as f:
                    storage = json.load(f)
                await ctx.add_cookies(storage.get("cookies", []))
                print("已載入 session.json")
                await page.goto(f"{TRAVIAN_URL}/dorf1.php", wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)
            except Exception as e:
                print(f"載入 session 失敗: {e}")

        # 如果還在登入頁，重新登入
        login_form = page.locator("form[name='login']")
        if await login_form.count() > 0 or "login" in page.url.lower():
            print("需要登入")
            await page.goto(f"{TRAVIAN_URL}/login.php", wait_until="domcontentloaded")
            await page.wait_for_timeout(1000)
            await page.fill("input[name='name']", USERNAME)
            await page.fill("input[name='password']", PASSWORD)
            await page.click("button[type='submit'], input[type='submit']")
            await page.wait_for_timeout(5000)

        print(f"目前 URL: {page.url}")

        # ========== 1. 先掃 dorf2 找出所有建築槽位 ==========
        print("\n=== 掃描 dorf2 建築槽位 ===")
        await page.goto(f"{TRAVIAN_URL}/dorf2.php", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        # dump all div class names to find building slots
        all_classes = await page.evaluate("""
        () => {
            const divs = [];
            document.querySelectorAll('div[id*="building"], div[class*="building"], div[id*="slot"], div[class*="slot"], div[id*="Slot"]').forEach(el => {
                divs.push(Array.from(el.classList).join(' ') + ' | id=' + (el.id || ''));
            });
            return divs.length > 0 ? divs : Array.from(document.querySelectorAll('div')).slice(0,50).map(d =>
                (d.id || '') + ' | ' + Array.from(d.classList).join(' ')
            ).filter(s => s.length > 5);
        }
        """)
        print(f"相關 div ({len(all_classes)} 個):")
        for c in all_classes[:30]:
            print(f"  {c}")

        # 嘗試所有 div 找 building slot 特徵
        slot_info = await page.evaluate("""
        () => {
            const results = [];
            document.querySelectorAll('div').forEach(el => {
                const cls = Array.from(el.classList).join(' ');
                const id = el.id || '';
                const allText = el.textContent.trim().slice(0, 100);
                // 尋找任何包含 aid 或 gid 或 level 或 building 的 div
                const aid = cls.match(/aid(\\d+)/);
                const g = cls.match(/\\bg(\\d+)\\b/);
                const level = cls.match(/level(\\d+)/);
                const hasBuildingIndicator = /(buildingSlot|aid|g\d+|level\d+)/.test(cls) || /(building|build)/.test(id);
                if (aid || g || level || hasBuildingIndicator) {
                    const nameEl = el.querySelector('.name, a[title]');
                    const name = nameEl ? (nameEl.getAttribute('title') || nameEl.textContent.trim()) : '';
                    const links = Array.from(el.querySelectorAll('a')).slice(0,3).map(a => ({
                        href: a.getAttribute('href') || '',
                        text: a.textContent.trim().slice(0,30)
                    }));
                    results.push({
                        id: id, cls: cls.slice(0,120),
                        aid: aid ? parseInt(aid[1]) : null,
                        gid: g ? parseInt(g[1]) : null,
                        level: level ? parseInt(level[1]) : null,
                        name: name.slice(0,40),
                        links: links,
                        text: allText.slice(0,60)
                    });
                }
            });
            return results;
        }
        """)
        print(f"\n建築相關元素 ({len(slot_info)} 個):")
        for s in slot_info[:20]:
            link_str = '; '.join(f"{l['text']}->{l['href'][:50]}" for l in s['links'] if l['href'])
            print(f"  id={s['id']!r} cls={s['cls'][:80]!r} aid={s['aid']} gid={s['gid']} Lv={s['level']} name={s['name']!r} links={link_str[:100]}")

        # ========== 2. 抓 Barracks (槽位 19 = GID 23 = Main Building. Wait, no...) ==========
        print(f"\n=== 分析槽位 ===")
        # 從上面結果看：a19 g23 aid19 → a=GID(19=Barracks), g=23(另一個ID?), aid=19(槽位)
        # 實際上 class 的順序是 buildingSlot {a}{gid} g{?} aid{slot} roman
        # 所以 a19 g23 aid19 表示 GID=19 (Barracks), 槽位=19
        # 那 g23 是什麼？可能是另一個編號系統
        
        # 先看 Barracks 的基礎頁面
        url = f"{TRAVIAN_URL}/build.php?id=19"
        print(f"導航到 Barracks: {url}")
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)

        html = await page.content()
        with open("debug_barracks.html", "w", encoding="utf-8") as f:
            f.write(html)
        await page.screenshot(path="debug_barracks.png")
        print("已儲存 debug_barracks.html + debug_barracks.png")

        # 檢查當前頁面是否有單位列表或訓兵表單
        page_info = await page.evaluate("""
        () => {
            const r = {
                title: document.title,
                h2: Array.from(document.querySelectorAll('h2, h1')).map(h => h.textContent.trim()),
                unitEls: document.querySelectorAll('[class*="unit"], [id*="unit"], .troop, .soldier').length,
                inputs: Array.from(document.querySelectorAll('input')).map(i => ({
                    name: i.name, id: i.id, type: i.type, classes: i.className.slice(0,40),
                    placeholder: i.placeholder, value: i.value
                })),
                buttons: Array.from(document.querySelectorAll('button')).map(b => ({
                    text: b.textContent.trim().slice(0,40), type: b.type, classes: b.className.slice(0,40)
                })),
                forms: Array.from(document.forms).map(f => ({
                    id: f.id, name: f.name, action: f.action ? f.action.slice(0,80) : '', method: f.method
                })),
                links: Array.from(document.querySelectorAll('nav a, [class*="tab"] a, .subMenu a')).slice(0,10).map(a => ({
                    text: a.textContent.trim().slice(0,30), href: a.getAttribute('href')?.slice(0,80)
                }))
            };
            return r;
        }
        """)
        print(f"標題: {page_info['title']}")
        print(f"H2: {page_info['h2']}")
        print(f"Inputs ({len(page_info['inputs'])}):")
        for i in page_info['inputs']:
            print(f"  name={i['name']!r} id={i['id']!r} type={i['type']!r}")
        print(f"Buttons ({len(page_info['buttons'])}):")
        for b in page_info['buttons']:
            if b['text'] or b['classes']:
                print(f"  text={b['text']!r} type={b['type']!r}")
        print(f"Forms ({len(page_info['forms'])}):")
        for f in page_info['forms']:
            print(f"  action={f['action'][:80]!r} method={f['method']!r}")
        print(f"頁內連結 ({len(page_info['links'])}):")
        for l in page_info['links']:
            if l['text'] or (l.get('href') and l['href']):
                print(f"  {l['text']:30s} -> {(l.get('href') or '')[:80]}")

        # ========== 3. 抓統計頁面的村莊分頁 ==========
        print("\n=== 統計頁面（村莊分頁）===")
        # Travian Legends 用 RESTful URL
        village_urls = [
            f"{TRAVIAN_URL}/statistics/village",
            f"{TRAVIAN_URL}/statistics/village/overview",
        ]
        for vu in village_urls:
            await page.goto(vu, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)
            print(f"URL: {page.url}")

            info = await page.evaluate("""
            () => {
                const rows = document.querySelectorAll('table tr');
                const sample = Array.from(rows).slice(1,8).map(r => Array.from(r.querySelectorAll('td')).map(c => c.textContent.trim()).join(' | '));
                const karteLinks = Array.from(document.querySelectorAll('a[href*="karte"]')).slice(0,10).map(a => ({
                    href: a.getAttribute('href'),
                    text: a.textContent.trim().slice(0,30)
                }));
                const coords = (document.body.textContent.match(/\\(-?\\d+\\|-?\\d+\\)/g) || []).slice(0,10);
                return { sampleRows: sample.filter(s => s.length > 0), karteLinks, coords, url: window.location.href };
            }
            """)
            print(f"  karte links: {len(info['karteLinks'])}, coords: {len(info['coords'])}")
            for r in info['sampleRows'][:5]:
                print(f"  {r[:150]}")
            for l in info['karteLinks'][:3]:
                print(f"  karte: {l['text']!r} -> {l['href']}")
            for c in info['coords'][:3]:
                print(f"  coord: {c}")
            if info['karteLinks'] or info['coords']:
                html = await page.content()
                with open("debug_stats_village.html", "w", encoding="utf-8") as f:
                    f.write(html)
                await page.screenshot(path="debug_stats_village.png", full_page=True)
                print("已儲存 debug_stats_village.html + .png")
                break

        # 也試試分頁
        for pg in [1, 2]:
            await page.goto(f"{TRAVIAN_URL}/statistics/village?page={pg}", wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            info2 = await page.evaluate("""
            () => {
                const rows = document.querySelectorAll('table tr');
                const sample = Array.from(rows).slice(1,5).map(r => Array.from(r.querySelectorAll('td')).map(c => c.textContent.trim()).join(' | '));
                const karteLinks = Array.from(document.querySelectorAll('a[href*="karte"]')).slice(0,5).map(a => ({
                    href: a.getAttribute('href'),
                    text: a.textContent.trim().slice(0,30)
                }));
                return { sample: sample.filter(s => s.length > 0), karteLinks };
            }
            """)
            print(f"\npage={pg}: {len(info2['sample'])} rows, {len(info2['karteLinks'])} karte links")
            for r in info2['sample'][:3]:
                print(f"  {r[:150]}")
            for l in info2['karteLinks'][:3]:
                print(f"  karte: {l['text']!r} -> {l['href']}")

        # ========== 4. 抓 Barracks 訓兵頁面 ==========
        print("\n=== Barracks 訓兵頁面 ===")
        # 槽位 19 是 Barracks，試試加參數
        for suffix in ['', '&t=1', '&s=1', '&mode=training', '&type=1']:
            url = f"{TRAVIAN_URL}/build.php?id=19{suffix}"
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            has_train = await page.evaluate("""
            () => ({
                hasUnitInputs: document.querySelectorAll('input[type="number"], input.trpInput').length > 0,
                inputs: Array.from(document.querySelectorAll('input')).map(i => ({
                    name: i.name, id: i.id, type: i.type, classes: i.className.slice(0,50)
                })),
                buttons: Array.from(document.querySelectorAll('button')).map(b => ({
                    text: b.textContent.trim().slice(0,40), type: b.type
                })),
                forms: Array.from(document.forms).slice(0,3).map(f => ({
                    action: f.action ? f.action.slice(0,80) : '', method: f.method
                }))
            })
            """)
            if has_train['hasUnitInputs']:
                print(f"找到訓兵頁面: {url}")
                for i in has_train['inputs']:
                    print(f"  input: name={i['name']!r} id={i['id']!r} type={i['type']!r}")
                for b in has_train['buttons']:
                    if b['text']:
                        print(f"  button: {b['text']!r}")
                for f in has_train['forms']:
                    print(f"  form: action={f['action']!r} method={f['method']!r}")
                html_train = await page.content()
                with open("debug_barracks_train.html", "w", encoding="utf-8") as f:
                    f.write(html_train)
                await page.screenshot(path="debug_barracks_train.png")
                print("已儲存 debug_barracks_train.html + .png")
                break
            else:
                print(f"  {url}: 無訓練輸入框")

        # ========== 5. 徹底分析統計頁面 ==========
        for opt, label in [(1, "player"), (2, "village"), (3, "ally"), (4, "hero"), (5, "natural")]:
            await page.goto(f"{TRAVIAN_URL}/statistics?opt={opt}", wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)

            info = await page.evaluate(f"""
            () => {{
                const tables = document.querySelectorAll('table');
                return {{
                    opt: {opt},
                    label: '{label}',
                    tableCount: tables.length,
                    tableClasses: Array.from(tables).slice(0,3).map(t => Array.from(t.classList).join(' ')),
                    sampleRows: Array.from(document.querySelectorAll('table tr')).slice(1,8).map(r => r.textContent.trim().slice(0, 180)),
                    karteLinks: Array.from(document.querySelectorAll('a[href*="karte"]')).slice(0,5).map(a => ({{
                        href: a.getAttribute('href'),
                        text: a.textContent.trim().slice(0,40),
                        title: a.getAttribute('title', '')?.slice(0,40) || ''
                    }})),
                    coordText: (document.body.textContent.match(/\\\(-?\d+\\\|-?\d+\\\)/g) || []).slice(0,10)
                }};
            }}
            """)
            print(f"\nopt={opt} ({label}): {info['tableCount']} tables, {len(info['karteLinks'])} karte links, {len(info['coordText'])} coords")
            for r in info['sampleRows'][:5]:
                if r.strip():
                    print(f"  {r[:150]}")
            for l in info['karteLinks'][:3]:
                print(f"  karte: {l['text']:30s} href={l['href'][:80]}")
            for c in info['coordText'][:3]:
                print(f"  coord: {c}")

            # 儲存 opt=2 頁面
            if opt == 2:
                html_stats = await page.content()
                with open("debug_stats_opt2.html", "w", encoding="utf-8") as f:
                    f.write(html_stats)
                await page.screenshot(path="debug_stats_opt2.png", full_page=True)
                print("已儲存 debug_stats_opt2.html + .png")

        await browser.close()
        print("\n✅ 診斷完成，請檢查 debug_*.html 和 debug_*.png")


asyncio.run(main())