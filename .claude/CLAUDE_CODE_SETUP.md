# Claude Code Custom Skills & Commands Setup

This project now has custom Claude Code integrations to save AI tokens on repetitive tasks.

---

## ✅ **What's Configured**

### 📁 **Project Structure**
```
.claude/
├── commands/          # Slash commands (explicit invocation)
│   └── push.md        # /push command
└── skills/           # Skills (automatic discovery)
    └── git-push/
        └── SKILL.md   # Auto git push skill
```

---

## 🚀 **How to Use**

### **Option 1: Slash Command** `/push` (Explicit)

Type the command directly in Claude Code CLI:

```
/push
/push Add new feature
/push "Fix bug in analyzer"
```

**When to use:** When you explicitly want to push code and prefer manual control.

---

### **Option 2: Skill** (Automatic)

Just ask naturally:

```
Push my changes
Commit and push
Upload to GitHub
Push these files to remote
```

Claude will automatically detect the intent and use the git-push skill.

**When to use:** When you want Claude to handle it intelligently based on context.

---

## 🔄 **How to Reload**

After creating or modifying skills/commands, restart Claude Code:

```bash
# Exit Claude Code (Ctrl+C or type 'exit')
# Then restart
claude-code
```

Or if running as a command:
```bash
# Just run your next command, changes are auto-detected
```

---

## 📊 **Skills vs Slash Commands**

| Feature | Slash Command | Skill |
|---------|--------------|-------|
| **Location** | `.claude/commands/*.md` | `.claude/skills/name/SKILL.md` |
| **Invocation** | Type `/command` | Ask naturally |
| **Discovery** | Manual | Automatic |
| **Format** | Single `.md` file | Directory with `SKILL.md` |
| **Best for** | Frequent explicit tasks | Context-aware automation |

---

## 🛠️ **Creating Your Own**

### Create a Slash Command

```bash
# 1. Create the file
cat > .claude/commands/mycommand.md << 'EOF'
---
description: What this command does
---

Instructions for Claude on how to execute this command.
EOF

# 2. Use it
/mycommand
```

### Create a Skill

```bash
# 1. Create directory and file
mkdir -p .claude/skills/my-skill
cat > .claude/skills/my-skill/SKILL.md << 'EOF'
---
name: my-skill
description: When Claude should use this skill
---

# My Skill

Instructions for when and how to use this skill.
EOF

# 2. Claude automatically discovers it
# Just ask naturally and Claude will use it when relevant
```

---

## 📚 **Example Skills in This Project**

### **Git Push** (`/push` or "push my changes")
- **Purpose:** Quick commit and push without wasting tokens
- **Usage:** `/push` or `/push "message"` or just ask "push my changes"
- **Saves:** ~100-200 tokens per push vs asking Claude manually

---

## 💡 **Pro Tips**

1. **Slash commands** are better for:
   - Tasks you do multiple times per session
   - When you want explicit control
   - Simple, repeatable actions

2. **Skills** are better for:
   - Complex workflows
   - Context-dependent actions
   - When you want Claude to decide automatically

3. **Both work together:**
   - You can have both a slash command AND a skill for the same task
   - Use whichever feels more natural in the moment

---

## 🔍 **Verify Setup**

Check if your skills/commands are loaded:

```bash
# List all files
ls -la .claude/commands/
ls -la .claude/skills/*/

# Should show:
# .claude/commands/push.md
# .claude/skills/git-push/SKILL.md
```

---

## 🐛 **Troubleshooting**

### Command not found: `/push`
1. Check file exists: `ls .claude/commands/push.md`
2. Restart Claude Code
3. Make sure filename is `.md` not `.yaml`

### Skill not auto-detected
1. Check directory structure: `.claude/skills/name/SKILL.md`
2. Filename must be exactly `SKILL.md` (all caps)
3. Restart Claude Code
4. Try being more explicit in your request

### Still not working?
Fall back to the always-reliable alternatives:
- `make push MSG='message'` (Makefile)
- `./git-push.sh 'message'` (Shell script)

---

## 📖 **Official Documentation**

For more details on Claude Code skills and commands:
- Claude Code documentation: https://github.com/anthropics/claude-code
- Skills guide: Check Claude Code CLI help with `claude-code --help`

---

**Last Updated:** January 4, 2026
