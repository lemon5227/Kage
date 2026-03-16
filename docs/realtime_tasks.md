# Realtime Tasks

Date: 2026-03-15
Scope: M2-1 realtime lane task taxonomy

## Realtime-first tasks

These should complete on the foreground lane whenever possible:

- system volume up/down/mute
- brightness up/down
- Wi-Fi on/off
- Bluetooth on/off
- screenshot
- undo last file operation
- open app
- short confirmation/cancel replies
- short weather lookup
- short video lookup / open latest result

## Why these belong to realtime

- short latency budget
- low ambiguity after intent normalization
- deterministic tool execution
- small reply payload

## Background-first tasks

These should move to the background lane once implemented:

- desktop cleanup
- download folder organization
- batch file rename/move
- long web research
- multi-step file editing
- long summaries or reports
- multi-tool reasoning with high uncertainty

## Current implementation scope

The first Realtime Lane extraction focuses on:

- deterministic command fastpath
- command confirmation / cancel / correction
- shared confirmation parsing utilities

Video/weather fastpaths remain in `core/server.py` for now and can be moved in
later iterations once the command path is stable.
