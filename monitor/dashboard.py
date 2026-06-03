import asyncio
from datetime import datetime, timezone
from typing import Optional

from rich import box
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, BarColumn, TextColumn
from rich.table import Table
from rich.text import Text
from loguru import logger

from database import db
from agent.plan_store import plan_store
from scheduler.loop import scheduler
from config import config


console = Console()


def build_dashboard() -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="footer", size=3)
    )
    layout["body"].split_row(
        Layout(name="left", ratio=2),
        Layout(name="right", ratio=1)
    )
    layout["body"]["left"].split_column(
        Layout(name="goal", size=6),
        Layout(name="resources", size=8),
        Layout(name="queue", size=5),
    )
    layout["body"]["right"].split_column(
        Layout(name="recent", size=10),
        Layout(name="next_action", size=3),
    )
    return layout


def render_dashboard(layout: Layout):
    header_text = Text("Travian AI Agent", style="bold cyan")
    uptime = ""
    if scheduler.start_time:
        delta = datetime.now(timezone.utc) - scheduler.start_time
        days = delta.days
        hours = delta.seconds // 3600
        minutes = (delta.seconds % 3600) // 60
        uptime = f"  已運行: {days}天 {hours}小時 {minutes}分鐘"
    status = "▶ 運行中" if not scheduler.paused else "⏸ 暫停中"
    status_style = "green" if not scheduler.paused else "yellow"
    header_text.append(uptime, style="white")
    header_text.append(f"  [{status}]", style=status_style)
    layout["header"].update(Panel(header_text, style="bold"))

    goal_panel = _render_goal_panel()
    layout["goal"].update(goal_panel)

    res_panel = _render_resource_panel()
    layout["resources"].update(res_panel)

    queue_panel = _render_queue_panel()
    layout["queue"].update(queue_panel)

    recent_panel = _render_recent_actions()
    layout["recent"].update(recent_panel)

    next_panel = _render_next_action()
    layout["next_action"].update(next_panel)

    footer_text = Text("[N] 新增指令  [P] 暫停/繼續  [L] 完整日誌  [Q] 退出", style="dim")
    layout["footer"].update(Panel(footer_text, style="dim"))


def _render_goal_panel() -> Panel:
    goal_text = "（無活躍目標 - 請按 N 輸入新目標）"
    progress_str = ""
    if plan_store.current_goal:
        goal_text = plan_store.current_goal.get("goal_text", str(plan_store.current_goal))
        total = len(plan_store.plan_steps) or 1
        current = plan_store.current_step_index
        pct = min(current / total * 100, 100)
        bar_len = 20
        filled = int(bar_len * pct / 100)
        bar = "█" * filled + "░" * (bar_len - filled)
        progress_str = f"\n進度: {current}/{total} {bar} {pct:.0f}%"

    plan_lines = []
    if plan_store.plan_steps:
        for i, step in enumerate(plan_store.plan_steps):
            if i < plan_store.current_step_index:
                prefix = "✅"
            elif i == plan_store.current_step_index:
                prefix = "▶"
            else:
                prefix = "  "
            plan_lines.append(f"{prefix} {step.get('description', '')}")

    content = Text(goal_text, style="bold white")
    if progress_str:
        content.append(progress_str, style="cyan")
    if plan_lines:
        content.append("\n" + "\n".join(plan_lines[:6]), style="dim")

    return Panel(content, title="當前目標", border_style="cyan")


def _render_resource_panel() -> Panel:
    state = scheduler.latest_state or {}
    res = state.get("resources", {})

    table = Table(box=box.SIMPLE, padding=(0, 1))
    table.add_column("資源", style="bold")
    table.add_column("數量", justify="right")
    table.add_column("上限", justify="right")
    table.add_column("產量", justify="right")

    res_data = [
        ("木材", res.get("wood", 0), res.get("warehouse_cap", "?"), res.get("wood_rate", 0)),
        ("黏土", res.get("clay", 0), res.get("warehouse_cap", "?"), res.get("clay_rate", 0)),
        ("鐵", res.get("iron", 0), res.get("warehouse_cap", "?"), res.get("iron_rate", 0)),
        ("糧食", res.get("crop", 0), res.get("granary_cap", "?"), res.get("crop_rate", 0)),
    ]
    wcap = res.get("warehouse_cap", 1)
    gcap = res.get("granary_cap", 1)
    for name, val, cap, rate in res_data:
        limit = cap if isinstance(cap, int) and cap > 0 else (wcap if name != "糧食" else gcap)
        pct = min(val / max(limit, 1) * 20, 20)
        bar = "█" * int(pct) + "░" * (20 - int(pct))
        display_val = f"{val:,}"
        display_cap = f"{limit:,}" if isinstance(limit, int) else str(limit)
        display_rate = f"+{rate}/h" if rate else "0/h"
        table.add_row(name, display_val, display_cap, display_rate)

    buildings = state.get("buildings", {})
    bld_text = ", ".join(f"{n}:Lv{l}" for n, l in sorted(buildings.items())[:6])

    content = Group(table, Text(f"\n{bld_text}", style="dim"))
    return Panel(content, title="資源與建築", border_style="green")


def _render_queue_panel() -> Panel:
    state = scheduler.latest_state or {}
    bq = state.get("build_queue", [])
    tq = state.get("troop_queue", [])

    lines = []
    for item in bq:
        name = item.get("name", "?")
        sl = item.get("seconds_left", 0)
        finish = item.get("finish_at", "")[11:16] if item.get("finish_at") else "?"
        duration = f"{sl // 3600}h{(sl % 3600) // 60}m" if sl > 0 else "?"
        lines.append(f"⏳ {name} Lv{item.get('level', '?')} 完成: {finish} (剩 {duration})")

    for item in tq:
        troop = item.get("troop", "?")
        count = item.get("count", 0)
        sl = item.get("seconds_left", 0)
        duration = f"{sl // 3600}h{(sl % 3600) // 60}m" if sl > 0 else "?"
        lines.append(f"⏳ 訓練 {count}x {troop} 剩 {duration}")

    if not lines:
        lines.append("（隊列空閒）")

    content = Text("\n".join(lines))
    return Panel(content, title="建造/訓練隊列", border_style="yellow")


def _render_recent_actions() -> Panel:
    lines = []
    for a in _cached_actions:
        ts = a.get("timestamp", "")[11:19]
        act = a.get("action_type", "")
        success = a.get("success", False)
        result = (a.get("result_text") or "")[:50]
        icon = "✅" if success else "❌"
        lines.append(f"{ts} {icon} {act}: {result}")

    if not lines:
        lines.append("（尚無記錄）")

    content = Text("\n".join(lines))
    return Panel(content, title="最近操作", border_style="magenta")


_cached_actions = []


def _render_next_action() -> Panel:
    state = scheduler.latest_state or {}
    nfs = state.get("next_free_slot")
    if nfs:
        try:
            dt = datetime.fromisoformat(nfs)
            local_str = dt.strftime("%H:%M")
            remaining = (dt - datetime.now(timezone.utc)).total_seconds()
            if remaining > 0:
                dur = f"{int(remaining // 3600)}h{int((remaining % 3600) // 60)}m"
                content = Text(f"下次行動: {local_str}（{dur}後）")
            else:
                content = Text("下次行動: 現在", style="green")
        except Exception:
            content = Text(f"下次行動: {nfs}")
    else:
        content = Text("下次行動: 5分鐘後")

    return Panel(content, border_style="blue")


async def _update_action_cache():
    global _cached_actions
    try:
        _cached_actions = await db.get_recent_actions(8)
    except Exception:
        pass


async def refresh_dashboard(layout: Layout):
    while scheduler.running:
        try:
            await _update_action_cache()
            render_dashboard(layout)
        except Exception as e:
            logger.error(f"儀表板更新失敗: {e}")
        await asyncio.sleep(5)


async def run_dashboard():
    layout = build_dashboard()
    try:
        with Live(layout, refresh_per_second=1, screen=True):
            while scheduler.running:
                await _update_action_cache()
                render_dashboard(layout)
                await asyncio.sleep(5)
    except Exception as e:
        logger.debug(f"儀表板結束: {e}")