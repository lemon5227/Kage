# Kage Skills

Kage uses markdown skills (`SKILL.md`) as *workflow templates*.

- Tools are implemented in `core/tools_impl.py` and registered in `core/tool_registry.py`.
- Skills describe *when* and *how* to use those tools.
- When Kage is unsure how to solve a task, it can search skills.sh (`npx skills find`),
  auto-install a suitable skill, load it, and continue executing.

## Local Skills Layout

Put local skills under:

- `skills/<skill-name>/SKILL.md`

Kage scans:

- `./skills/**/SKILL.md`
- `~/.kage/skills/**/SKILL.md`
- `~/.config/opencode/skills/**/SKILL.md` (skills installed by `npx skills add -g -a opencode`)

## SKILL.md Format

Kage supports the Agent Skills format (YAML frontmatter):

```md
---
name: my-skill
description: What this skill does.
---

# My Skill

Steps...
```

## Safety Policy

- Only deletion-like operations require confirmation.
- Non-delete file operations are recorded in the undo log and can be reverted.
