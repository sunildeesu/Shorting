---
name: git-push
description: Commits and pushes code changes to remote repository. Use when user asks to push changes, commit code, or upload to GitHub.
---

# Git Push Skill

Automatically commits and pushes code changes when the user asks to push, commit, or upload code.

## When to Use

This skill should be used when the user:
- Says "push my changes"
- Says "commit and push"
- Says "upload to GitHub"
- Says "push to remote"
- Asks to save code changes to git

## How to Execute

1. **Check current status:**
   ```bash
   git status --short
   ```

2. **Generate commit message:**
   - Count changed files
   - Identify file types (Python, markdown, config, etc.)
   - Create descriptive message: "Update X files - YYYY-MM-DD"
   - Or use user-provided message if they specified one

3. **Execute git workflow:**
   ```bash
   git add -A
   git commit -m "Generated message"
   git push
   ```

4. **Confirm success:**
   - Show commit hash
   - Show number of files changed
   - Confirm pushed to remote

## Important Notes

- Be efficient and concise (minimize token usage)
- Follow project's commit message format with co-author footer
- Don't ask for confirmation unless sensitive files are modified
- If push fails (merge conflicts, need to pull), provide the fix

## Example Interaction

**User:** "Push my changes"

**Assistant:**
- Checks status: 3 files modified
- Generates message: "Update 3 files - 2026-01-04"
- Adds, commits, and pushes
- Confirms: "✅ Pushed commit abc123 (3 files changed)"
