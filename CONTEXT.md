# Travian AI Agent — Domain Context

## Project

A Playwright-based autonomous bot for Travian Legends. Controls a browser to log in, parse game state from HTML, make LLM-driven decisions, and execute actions (build, train, attack).

## Architecture Layers

```
main.py → scheduler/loop.py → agent/decision.py → LLM
                              → executor/*.py     → browser
                              → parser/*.py       → state dict
                              → scraper/*.py      → browser lifecycle
```

- **scraper/** — Browser lifecycle (launch, login, session persistence, page navigation)
- **parser/** — HTML → structured data (resources, buildings, queues, troops, map)
- **executor/** — In-game actions via browser manipulation (build, train, attack)
- **agent/** — Decision-making: LLM integration, memory, planning, reflection, intel
- **scheduler/** — Orchestration loop: get state → decide → execute → sleep
- **database/** — SQLite persistence for states, actions, goals, intel

## Key Concepts

### Game State
The canonical state dict built by `parser/state_builder.build_game_state()`. Consumed by `agent/decision.py`, `scheduler/loop.py`, `executor/train.py`, and `agent/knowledge_base.py`. Typed as `GameState` in `state_builder.py`.

Fields: timestamp, village_name, resources, buildings, buildings_with_slots, resource_fields, empty_building_slots, coord_x/y, build_queue, build_queue_full, troop_queue, troops, map, next_free_slot, has_plus, hero, quests, diplomatic_intel.

### Build Queue
Up to 1 item (free) or 2 items (Travian Plus). Checked via `state.build_queue_full`. Three modules originally computed this independently — now centralized in `build_game_state()`.

### Building Identification
- GID: Game ID, the building type (e.g. Barracks = 19, Cranny = 23)
- Slot: Position on the dorf2 grid (aid in HTML class). Buildings can be in any slot.
- Class format: `buildingSlot a{slot} g{gid} aid{slot} roman`

### Map Scanning
Travian Legends uses PixiJS (WebGL Canvas) for karte.php — cannot parse via HTML. Instead, `/statistics/village?page=N` provides a traditional HTML table with player/village/coordinates/ally/population columns.

### LLM Actions
Defined in `agent/llm_client.py` as `LLM_TOOLS`. 現有十個動作:
- upgrade_building, upgrade_resource_field (建造)
- train_troops (訓兵)
- send_attack, send_scout (軍事)
- collect_hero_resources, send_hero_on_adventure, allocate_hero_points (英雄)
- collect_quest_reward (任務)
- wait, complete (控制流程)

Dispatched in `scheduler/loop.py:_execute_single_action()`.
優先級前置動作 (不經 LLM) 在 `_pre_loop_priority_checks()` 中處理。

## File Layout

```
root/
├── main.py               # Entry point
├── config.py              # Dataclass config from .env
├── database.py            # SQLite
├── agent/
│   ├── decision.py        # AutonomousBrain → formats state → calls LLM
│   ├── intel.py           # IntelManager → map scanning, threat assessment, diplomatic intelligence (build_diplomatic_intel)
│   ├── knowledge_base.py  # Cost tables, build recommendations
│   ├── llm_client.py      # LLM API client, tool definitions
│   ├── memory.py          # Summary-based memory compression
│   ├── planner.py         # Goal management
│   └── reflection.py      # Periodic self-reflection
├── executor/
│   ├── attack.py          # send_attack / send_scout
│   ├── build.py           # upgrade_building / upgrade_resource_field
│   ├── hero.py            # collect_hero_resources / send_hero_adventure / allocate_hero_points
│   ├── navigation.py      # URL helpers → navigate_to / navigate_to_build
│   ├── quests.py          # collect_quest_reward
│   ├── scout.py           # Thin re-export of attack.send_scout
│   └── train.py           # train_troops
├── parser/
│   ├── buildings.py       # dorf2 HTML → buildings dict + buildings_with_slots
│   ├── hero.py            # parse_hero_state → hero status, items, adventures, rewards
│   ├── map_scanner.py     # HTML/JS map parsing (legacy)
│   ├── quests.py          # parse_quests → daily/main quests, reward readiness
│   ├── queue.py           # Build / troop queue parsing
│   ├── resources.py       # dorf1 HTML → resource numbers + rates
│   ├── state_builder.py   # Orchestrates all parsers → GameState
│   └── troops.py          # Home / away troop parsing
├── scheduler/
│   └── loop.py            # Main loop: state → decide → execute
└── scraper/
    ├── browser.py          # Playwright BrowserManager singleton
    ├── login.py            # Session + cookie management
    └── page_reader.py      # Convenience wrapper
```

## ADRs

See `docs/adr/`. (None yet.)