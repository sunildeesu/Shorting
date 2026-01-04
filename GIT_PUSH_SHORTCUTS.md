# Git Push Shortcuts - Save AI Tokens!

Three ways to quickly push code without using AI tokens every time.

---

## 🚀 Option 1: Claude Code Skill (RECOMMENDED)

**What it is:** A reusable skill you can invoke with a slash command

**Setup:** Already done! ✅ Skill created at `.claude/skills/push.yaml`

**Usage:**
```bash
/push
# Auto-generates commit message and pushes

/push "Add new feature"
# Uses your custom message and pushes
```

**Advantages:**
- ✅ Works directly in Claude Code CLI
- ✅ No need to switch to terminal
- ✅ Minimal token usage (just invokes the skill)
- ✅ Handles edge cases (merge conflicts, etc.)
- ✅ Smart commit message generation

---

## 🔧 Option 2: Shell Script

**What it is:** A bash script that automates the git workflow

**Location:** `git-push.sh` (already created and executable)

**Usage:**
```bash
# From project directory
./git-push.sh
# Shows status, auto-generates message, asks confirmation, then pushes

./git-push.sh "Your commit message here"
# Uses your custom message
```

**Create a global alias (optional):**

Add to your `~/.zshrc` or `~/.bashrc`:
```bash
alias gp='~/myProjects/ShortIndicator/git-push.sh'
```

Then reload:
```bash
source ~/.zshrc  # or source ~/.bashrc
```

Now you can use:
```bash
gp
gp "Custom message"
```

**Advantages:**
- ✅ Works in any terminal
- ✅ Colorful output with status checks
- ✅ Confirmation prompts
- ✅ No AI tokens used at all

---

## ⚡ Option 3: Git Alias (Fastest)

**What it is:** Built-in git shortcuts

**Setup:**
```bash
# Quick push (auto-message with date)
git config --global alias.qp '!git add -A && git commit -m "Update $(date +%Y-%m-%d)" && git push'

# Smart push (shows status first)
git config --global alias.sp '!f() { git status; git add -A; git commit -m "${1:-Update $(date +%Y-%m-%d)}"; git push; }; f'
```

**Usage:**
```bash
git qp
# Quick push with auto-generated message

git sp "Your message"
# Smart push with custom message
```

**Advantages:**
- ✅ Ultra-fast (2-3 characters)
- ✅ Works in any git repository
- ✅ No external scripts needed
- ✅ Zero AI tokens

---

## 📊 Comparison

| Method | Speed | Token Usage | Flexibility | Setup |
|--------|-------|-------------|-------------|-------|
| **Claude Skill** `/push` | Medium | Minimal | High | Done ✅ |
| **Shell Script** `./git-push.sh` | Fast | Zero | Medium | Done ✅ |
| **Git Alias** `git qp` | Fastest | Zero | Low | Need to run setup |

---

## 🎯 Recommended Workflow

### For this project:
```bash
# Use Claude Code skill when you're already in the CLI
/push "Add color coding"

# Or use shell script in terminal
./git-push.sh "Add color coding"
```

### Make it even easier (create alias):

Add to `~/.zshrc`:
```bash
alias push='~/myProjects/ShortIndicator/git-push.sh'
```

Then just:
```bash
push "Add feature"
```

---

## 🔥 Pro Tip: Combine with Pre-commit Hooks

The git-push script already:
- ✅ Shows git status before pushing
- ✅ Asks for confirmation
- ✅ Handles errors gracefully
- ✅ Auto-generates descriptive messages

For even more automation, you could add a pre-commit hook to run tests automatically!

---

## 📝 Examples

### Using Claude Skill:
```
You: /push "Implement weekly backtest automation"
Claude: [Runs git workflow, shows summary, pushes]
```

### Using Shell Script:
```bash
$ ./git-push.sh "Implement weekly backtest automation"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      Quick Git Push Script
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 Current Status:
 M telegram_notifier.py
 M weekly_backtest_runner.py
?? git-push.sh

💬 Using provided message: Implement weekly backtest automation

Continue with push? [y/N]: y

📦 Adding files...
💾 Committing...
🚀 Pushing to remote...

✅ Successfully pushed to remote!
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Using Git Alias:
```bash
$ git qp
# Instantly pushes with "Update 2026-01-04" message
```

---

**Choose your preferred method and save those AI tokens for actual development work! 🚀**
