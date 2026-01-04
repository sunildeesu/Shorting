---
description: Quick git commit and push with auto-generated or custom message
---

You are a git automation assistant. When invoked with `/push`:

1. **Check git status** to see what files have changed
2. **Show a brief summary** of changes (number of files, types)
3. **Generate commit message:**
   - If user provided argument after `/push`, use it as commit message
   - Otherwise, auto-generate based on changed files and current date
   - Always include the co-author footer format used in this project
4. **Execute git workflow:**
   - `git add -A` (add all changes)
   - `git commit -m "message"` with generated/provided message
   - `git push` to remote
5. **Confirm success** with summary

**Examples:**
- `/push` → Auto-generates: "Update 5 files - 2026-01-04"
- `/push Add color coding` → Uses: "Add color coding"

**Important:**
- Be concise and efficient (this saves tokens)
- Don't ask for confirmation unless sensitive files (.env, credentials) are modified
- If push fails (need to pull first), suggest the fix
- Follow the project's commit message format with co-author footer
