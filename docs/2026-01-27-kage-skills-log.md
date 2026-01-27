# 2026-01-27 Kage Skills Implementation Log

## Summary
- Unified external skill ingestion via `skills/claude_skill_importer.py` and `outer_skills/`.
- Added MCP + daily utility skills and expanded triggers for Chinese prompts.
- Added Vercel/Anthropic/Marketing skills conversion with SKILL.md guidance loading.
- Integrated Playwright skill with auto-detect + URL execution flow.
- Stabilized chat responses and added smoke tests.

## Skills Added/Updated
- Daily skills: `battery_status`, `system_uptime`, `weather_brief`, `today_date`, `open_notes`, `joke`.
- MCP skills: `mcp_client`, `mcp_fs_list`, `mcp_fs_read`, `mcp_fs_write`.
- Imported skills: `find_skills`, `social_content`, `pptx`, `docx`, `xlsx`, `pdf`, `playwright_skill`.

## External Skills Workflow
- Install: `npx skills add <repo> --skill <name> -g -y`
- Copy to `outer_skills/`
- Convert: `python3 skills/claude_skill_importer.py`
- Restart Kage to reload skills.

## Playwright Skill Execution
- Auto-detect servers: `{"detect_servers": true}`
- Run with URL: `{"url": "https://example.com", "headless": false, "timeout": 30}`
- If no URL is provided, auto-detect runs first:
  - 1 server -> auto execute
  - multiple servers -> ask user
  - none -> ask for URL
- Error handling: checks `run.js` and `node_modules` before execution.

## Tests Run
- `python3 scripts/kage_text_smoke_test.py`
- `python3 scripts/kage_chat_smoke_test.py`
- `python3 scripts/skills_smoke_test.py`

## Notes
- External skills are stored under `outer_skills/` and ignored by git.
- Playwright skill requires `npm run setup` in `outer_skills/playwright-skill`.

## Follow-up Updates
- Added `brightness_control` and `open_browser` skills to bypass LLM latency for common commands.
- Added Playwright auto-detect flow to run browser automation when URL is omitted.
- Added pre-router trigger shortcut to execute fast skills before intent classification.
- Added pre-router fast commands for weather/time and quick URL opens (baidu/https links).
- Added pre-router direct app open using installed-app registry for "打开/启动" commands.
- Added app alias mapping in `open_app` for common Chinese names (WeChat, QQ, Lark, etc.).
- Added `scripts/fast_command_benchmark.py` to measure fast-path latency.
- Weather: cache results 10 minutes, cache local city 24h, background prefetch local city at startup.
- Direct system controls: volume, brightness, bluetooth, wifi now bypass router.
- Media control prefers app-level AppleScript; NetEase uses activate + media key fallback.
- Weather fast path uses curl --max-time with cache fallback; IP city lookup now 4s timeout.
