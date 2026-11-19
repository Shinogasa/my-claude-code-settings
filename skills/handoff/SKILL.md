---
name: handoff
description: Compact the current conversation into a handoff document for another agent to pick up.
argument-hint: "What will the next session be used for?"
disable-model-invocation: true
---

Write a handoff document summarising the current conversation so a fresh agent can continue the work. Save it to `tasks/handoff/<short-kebab-name>.md` under the top of the current git repository (`git rev-parse --show-toplevel`): there it survives restarts and is visible from a devcontainer that mounts the repository. Before writing, run `git check-ignore -q tasks/handoff/<short-kebab-name>.md` from that top. If it exits non-zero (the path is tracked by git, or there is no repository), stop and ask the user where to save it. Report the saved path.

Include a "suggested skills" section in the document, naming which skills the next agent should call the Skill tool for.

Do not duplicate content already captured in other artifacts (specs, plans, ADRs, issues, commits, diffs). Reference them by path or URL instead.

Redact any sensitive information, such as API keys, passwords, or personally identifiable information.

If the user passed arguments, treat them as a description of what the next session will focus on and tailor the doc accordingly.
