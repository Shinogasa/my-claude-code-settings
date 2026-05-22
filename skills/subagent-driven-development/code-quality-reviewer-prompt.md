# Code Quality Reviewer Prompt Template

Verify the implementation is well-built: clean, tested, maintainable.

**Only dispatch after spec compliance review passes.**

```
Agent tool (general-purpose):
  description: "Review code quality for Task N"
  prompt: |
    You are reviewing code quality for a task implementation.

    ## What Was Implemented

    [From implementer's report]

    ## Files Changed

    [List of files or git diff range: BASE_SHA..HEAD_SHA]

    ## Review Criteria

    **Architecture:**
    - Does each file have one clear responsibility?
    - Are units decomposed for independent understanding and testing?
    - Does the implementation follow the file structure from the plan?

    **Code Quality:**
    - Clean, readable, well-named
    - No deep nesting (>4 levels)
    - Functions under 50 lines
    - Immutable patterns used (no mutation)
    - Proper error handling

    **Testing:**
    - Tests verify behavior, not implementation details
    - Edge cases and error paths covered
    - No unnecessary mocks

    **Maintainability:**
    - Follows existing codebase patterns
    - No magic numbers or hardcoded values
    - DRY without premature abstraction

    ## Report Format

    **Strengths:** [What was done well]

    **Issues:**
    - Critical: [Must fix before merge]
    - Important: [Should fix]
    - Minor: [Nice to fix]

    **Assessment:** Approved | Needs Changes
```
