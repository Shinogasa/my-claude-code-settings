---
description: Legacy slash-entry shim for the superpowers:test-driven-development skill. Prefer the skill directly.
---

# TDD Command (Legacy Shim)

Use this only if you still invoke `/tdd`. The maintained workflow is the
`superpowers:test-driven-development` skill provided by the superpowers plugin.

## Arguments

`$ARGUMENTS`

## Delegation

Apply the `superpowers:test-driven-development` skill.
- Stay strict on RED -> GREEN -> REFACTOR, and watch each test fail before implementing.
- Follow `rules/ecc-testing.md` for coverage and the Git checkpoint commits per stage.
