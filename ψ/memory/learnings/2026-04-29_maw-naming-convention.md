# Lesson: maw Oracle Naming Convention

**Date**: 2026-04-29
**Source**: pm-oracle /rrr
**Context**: Consolidating broky-oracle + metty-oracle into god-port-oracle

## Pattern

maw expects GitHub repos to follow the naming convention `{name}-oracle`. When creating a fleet entry for `XX-name`, maw scans for `{name}-oracle` on GitHub.

- `00-emily` → looks for `emily-oracle` ✓
- `01-god-port` → looks for `god-port-oracle` ✓ (after rename from `god-port-trading`)
- `02-pm` → looks for `pm-oracle` ✓

## What Went Wrong

Initially named the repo `god-port-trading` (user's choice). When running `maw wake 03-god-port`, maw scanned for `03-god-port-oracle` and `god-port-oracle` — neither existed. The `-trading` suffix broke the convention.

## Fix

Renamed GitHub repo from `god-port-trading` to `god-port-oracle`. Updated git remote and local folder name.

## Rule

**When creating repos for maw integration, always use the `{name}-oracle` naming convention.** The `-oracle` suffix is required by maw's repo discovery logic.

## Secondary Lesson

When consolidating oracle repos, immediately:
1. Remove old fleet entries (broky, metty)
2. Renumber fleet sequentially (00, 01, 02)
3. Update all CLAUDE.md and vault path references
4. Test `maw wake {name}` before declaring done