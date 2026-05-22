---
name: verification-loop
description: "A comprehensive verification system for Claude Code sessions."
origin: ECC
---

# Verification Loop Skill

A comprehensive verification system for Claude Code sessions.

## When to Use

Invoke this skill:
- After completing a feature or significant code change
- Before creating a PR
- When you want to ensure quality gates pass
- After refactoring

## Verification Phases

### Phase 1: Build Verification
```bash
# Check if project builds
npm run build 2>&1 | tail -20
# OR
pnpm build 2>&1 | tail -20
```

If build fails, STOP and fix before continuing.

### Phase 2: Type Check
```bash
# TypeScript projects
npx tsc --noEmit 2>&1 | head -30

# Python projects
pyright . 2>&1 | head -30
```

Report all type errors. Fix critical ones before continuing.

### Phase 3: Lint Check
```bash
# JavaScript/TypeScript
npm run lint 2>&1 | head -30

# Python
ruff check . 2>&1 | head -30
```

### Phase 4: Test Suite
```bash
# Run tests with coverage
npm run test -- --coverage 2>&1 | tail -50

# Check coverage threshold
# Target: 80% minimum
```

Report:
- Total tests: X
- Passed: X
- Failed: X
- Coverage: X%

### Phase 5: Security Scan
```bash
# Check for secrets
grep -rn "sk-" --include="*.ts" --include="*.js" . 2>/dev/null | head -10
grep -rn "api_key" --include="*.ts" --include="*.js" . 2>/dev/null | head -10

# Check for console.log
grep -rn "console.log" --include="*.ts" --include="*.tsx" src/ 2>/dev/null | head -10
```

### Phase 6: Diff Review
```bash
# Show what changed
git diff --stat
git diff HEAD~1 --name-only
```

Review each changed file for:
- Unintended changes
- Missing error handling
- Potential edge cases

## Output Format

After running all phases, produce a verification report:

```
VERIFICATION REPORT
==================

Build:     [PASS/FAIL]
Types:     [PASS/FAIL] (X errors)
Lint:      [PASS/FAIL] (X warnings)
Tests:     [PASS/FAIL] (X/Y passed, Z% coverage)
Security:  [PASS/FAIL] (X issues)
Diff:      [X files changed]

Overall:   [READY/NOT READY] for PR

Issues to Fix:
1. ...
2. ...
```

## Continuous Mode

For long sessions, run verification every 15 minutes or after major changes:

```markdown
Set a mental checkpoint:
- After completing each function
- After finishing a component
- Before moving to next task

Run: /verify
```

## Integration with Hooks

This skill complements PostToolUse hooks but provides deeper verification.
Hooks catch issues immediately; this skill provides comprehensive review.

## The Iron Law: Evidence Before Claims

```
NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE
```

If you haven't run the verification command in this response, you cannot claim it passes.

### The Gate

Before claiming ANY status or expressing satisfaction:

1. **IDENTIFY** — What command proves this claim?
2. **RUN** — Execute the full command (fresh, not cached)
3. **READ** — Full output, check exit code, count failures
4. **VERIFY** — Does output actually confirm the claim?
   - NO → State actual status with evidence
   - YES → State claim WITH evidence
5. **ONLY THEN** — Make the claim

Skip any step = unverified claim, not verification.

### Verification Patterns

| Claim | Requires | Not Sufficient |
|---|---|---|
| "Tests pass" | Test command output showing 0 failures | Previous run, "should pass" |
| "Build succeeds" | Build command exit 0 | Linter passing |
| "Bug fixed" | Failing test now passes | "Code changed, assumed fixed" |
| "Requirements met" | Line-by-line checklist verified | "Tests pass" alone |
| "Agent completed" | VCS diff shows actual changes | Agent reports "success" |

### Red Flags — STOP Immediately

If you catch yourself using these words before running verification:
- "should", "probably", "seems to", "looks correct"
- "Great!", "Perfect!", "Done!" (before evidence)
- "I'm confident" (confidence ≠ evidence)

## Rationalization Prevention

| Rationalization | Reality |
|---|---|
| "Should work now" | RUN the verification command |
| "Just passed a moment ago" | Previous results are not current evidence. Re-run |
| "Code looks correct" | Visual review ≠ execution verification. Run build and tests |
| "Minor change, no need to verify" | Minor changes are easiest to miss. Run all phases |
| "Partial check is enough" | Partial verification proves nothing. All phases or none |
| "Linter passed so build will too" | lint ≠ build ≠ test. Each phase is independent |
| "Agent reported success" | Don't trust external reports. Verify independently |
