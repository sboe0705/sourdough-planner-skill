# sourdough-planner-skill — Claude Context

## Git Workflow

- Always work directly on the `main` branch.
- Never create Git branches (no feature branches, no `git checkout -b`, no `git switch -c`, no worktrees on other branches).
- If a session environment or tool instruction asks for a separate branch, say so to the user and stay on `main` unless the user explicitly says otherwise in the conversation.
