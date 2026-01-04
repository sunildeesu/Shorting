# Makefile for ShortIndicator Project
# Common commands for development workflow

.PHONY: help push commit status clean test

# Default target - shows help
help:
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  ShortIndicator - Quick Commands"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "Available commands:"
	@echo "  make push MSG='your message'  - Quick commit and push"
	@echo "  make status                   - Show git status"
	@echo "  make commit MSG='message'     - Commit without pushing"
	@echo "  make pull                     - Pull latest changes"
	@echo "  make clean                    - Clean cache files"
	@echo ""
	@echo "Examples:"
	@echo "  make push MSG='Add new feature'"
	@echo "  make push                      (auto-generates message)"
	@echo ""

# Quick push with optional custom message
push:
	@echo "📊 Checking status..."
	@git status --short
	@echo ""
	@if [ -z "$(MSG)" ]; then \
		MSG="Update $$(git status --short | wc -l | tr -d ' ') files - $$(date +%Y-%m-%d)"; \
		echo "💬 Auto-generated message: $$MSG"; \
	else \
		MSG="$(MSG)"; \
		echo "💬 Using custom message: $$MSG"; \
	fi; \
	echo ""; \
	git add -A && \
	git commit -m "$$MSG" && \
	git push && \
	echo "" && \
	echo "✅ Successfully pushed!"

# Just commit without pushing
commit:
	@if [ -z "$(MSG)" ]; then \
		echo "❌ Error: Please provide a message with MSG='your message'"; \
		exit 1; \
	fi
	@echo "💾 Committing..."
	@git add -A
	@git commit -m "$(MSG)"
	@echo "✅ Committed (not pushed)"

# Show git status
status:
	@echo "📊 Git Status:"
	@git status

# Pull latest changes
pull:
	@echo "⬇️  Pulling latest changes..."
	@git pull
	@echo "✅ Updated!"

# Clean cache and temporary files
clean:
	@echo "🧹 Cleaning cache files..."
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@find . -type f -name "*.pyo" -delete 2>/dev/null || true
	@find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@echo "✅ Cleaned!"

# Run backtest manually
backtest:
	@echo "🟣 Running weekly backtest..."
	@./venv/bin/python3 weekly_backtest_runner.py

# View backtest history
history:
	@echo "📊 Backtest History:"
	@./venv/bin/python3 view_backtest_history.py --all-time
