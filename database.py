import json
import sqlite3
import aiosqlite
from datetime import datetime, timezone
from typing import Optional

from config import config
from loguru import logger


class Database:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(config.db_path)
        self._conn: Optional[sqlite3.Connection] = None
        self._initialized = False

    def get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def init_db(self):
        if self._initialized:
            return
        try:
            conn = self.get_conn()
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS game_states (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    state_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS goals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    goal_text TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    plan_json TEXT
                );
                CREATE TABLE IF NOT EXISTS actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    action_params TEXT,
                    success INTEGER NOT NULL DEFAULT 0,
                    result_text TEXT,
                    screenshot_path TEXT
                );
                CREATE TABLE IF NOT EXISTS llm_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    prompt_tokens INTEGER DEFAULT 0,
                    completion_tokens INTEGER DEFAULT 0,
                    model TEXT,
                    response_json TEXT
                );
                CREATE TABLE IF NOT EXISTS summary_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    summary_text TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS map_intel (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    coord_x INTEGER,
                    coord_y INTEGER,
                    player_name TEXT,
                    alliance TEXT,
                    population INTEGER,
                    village_name TEXT,
                    last_scouted_at TIMESTAMP,
                    scout_report TEXT,
                    is_farmable INTEGER DEFAULT 0,
                    threat_level TEXT DEFAULT 'unknown',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS autonomous_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_type TEXT,
                    priority INTEGER DEFAULT 5,
                    description TEXT,
                    params TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS build_plans (
                    plan_id TEXT PRIMARY KEY,
                    created_at REAL NOT NULL,
                    strategic_goal TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    replan_trigger TEXT,
                    valid_for_hours REAL,
                    status TEXT NOT NULL DEFAULT 'active',
                    invalidated_reason TEXT
                );
            """)
            conn.commit()
            self._initialized = True
            logger.info("資料庫初始化完成")
        except sqlite3.Error as e:
            logger.error(f"資料庫初始化失敗: {e}")
            raise

    async def save_state(self, state: dict):
        ts = state.get("timestamp", datetime.now(timezone.utc).isoformat())
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO game_states (timestamp, state_json) VALUES (?, ?)",
                (ts, json.dumps(state, ensure_ascii=False))
            )
            await db.commit()

    async def save_goal(self, goal_text: str, plan_json: str = None) -> int:
        ts = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "INSERT INTO goals (created_at, goal_text, status, plan_json) VALUES (?, ?, 'active', ?)",
                (ts, goal_text, plan_json)
            )
            await db.commit()
            return cur.lastrowid

    async def get_active_goal(self) -> Optional[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM goals WHERE status = 'active' ORDER BY id DESC LIMIT 1"
            )
            row = await cur.fetchone()
            if row:
                return dict(row)
            return None

    async def complete_goal(self, goal_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE goals SET status = 'completed' WHERE id = ?", (goal_id,))
            await db.commit()

    async def cancel_goals(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE goals SET status = 'cancelled' WHERE status = 'active'")
            await db.commit()

    async def log_action(self, action_type: str, action_params: dict, success: bool,
                         result_text: str = "", screenshot_path: str = None):
        ts = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO actions (timestamp, action_type, action_params, success, result_text, screenshot_path) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (ts, action_type, json.dumps(action_params, ensure_ascii=False),
                 int(success), result_text, screenshot_path)
            )
            await db.commit()

    async def log_llm_call(self, prompt_tokens: int, completion_tokens: int,
                           model: str, response_json: str):
        ts = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO llm_calls (timestamp, prompt_tokens, completion_tokens, model, response_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (ts, prompt_tokens, completion_tokens, model, response_json)
            )
            await db.commit()

    async def get_recent_actions(self, limit: int = 10) -> list:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM actions ORDER BY id DESC LIMIT ?", (limit,)
            )
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def get_recent_states(self, limit: int = 5) -> list:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM game_states ORDER BY id DESC LIMIT ?", (limit,)
            )
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def save_summary(self, summary_text: str):
        ts = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO summary_memory (timestamp, summary_text) VALUES (?, ?)",
                (ts, summary_text)
            )
            await db.commit()

    async def get_latest_summary(self) -> Optional[str]:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT summary_text FROM summary_memory ORDER BY id DESC LIMIT 1"
            )
            row = await cur.fetchone()
            return row[0] if row else None

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    async def get_all_goals(self) -> list:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM goals ORDER BY id DESC")
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def save_map_intel(self, data: dict):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT OR REPLACE INTO map_intel
                   (coord_x, coord_y, player_name, population, village_name, updated_at)
                   VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (data.get("coord_x"), data.get("coord_y"),
                 data.get("player_name"), data.get("population"),
                 data.get("village_name"))
            )
            await db.commit()

    async def get_map_intel(self, limit: int = 50) -> list:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM map_intel ORDER BY updated_at DESC LIMIT ?", (limit,)
            )
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def save_task(self, task_type: str, description: str, params: dict = None,
                        priority: int = 5) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "INSERT INTO autonomous_tasks (task_type, description, params, priority, status) "
                "VALUES (?, ?, ?, ?, 'pending')",
                (task_type, description, json.dumps(params or {}, ensure_ascii=False), priority)
            )
            await db.commit()
            return cur.lastrowid

    async def get_pending_tasks(self, limit: int = 10) -> list:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM autonomous_tasks WHERE status = 'pending' ORDER BY priority ASC, id ASC LIMIT ?",
                (limit,)
            )
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


db = Database()