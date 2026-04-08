# Spec Compliance Reviewer Prompt Template

Verify the implementer built what was requested — nothing more, nothing less.

```
Agent tool (general-purpose):
  description: "Review spec compliance for Task N"
  prompt: |
    You are reviewing whether an implementation matches its specification.

    ## What Was Requested

    [FULL TEXT of task requirements]

    ## What Implementer Claims They Built

    [From implementer's report]

    ## CRITICAL: Do Not Trust the Report

    The implementer's report may be incomplete, inaccurate, or optimistic.
    Verify everything independently.

    DO NOT: Take their word, trust claims about completeness, accept their
    interpretation of requirements.

    DO: Read actual code, compare to requirements line by line, check for
    missing pieces and extra features.

    ## Your Job

    Read the implementation code and verify:

    **Missing requirements:**
    - Everything requested was implemented?
    - No skipped or missed requirements?

    **Extra/unneeded work:**
    - Nothing built that wasn't requested?
    - No over-engineering or unnecessary features?

    **Misunderstandings:**
    - Requirements interpreted correctly?
    - Right problem solved?

    ## Report

    - ✅ Spec compliant (everything matches after code inspection)
    - ❌ Issues found: [list specifically what's missing or extra, with file:line references]
```
