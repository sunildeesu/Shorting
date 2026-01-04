#!/bin/bash
# Quick Git Push Script
# Usage: ./git-push.sh "Your commit message" (optional)
# If no message provided, auto-generates one

set -e  # Exit on error

# Color codes for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}      Quick Git Push Script${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Check if we're in a git repo
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    echo -e "${RED}❌ Not a git repository${NC}"
    exit 1
fi

# Show current status
echo -e "\n${BLUE}📊 Current Status:${NC}"
git status --short

# Get commit message
if [ -z "$1" ]; then
    # Auto-generate commit message based on changed files
    CHANGED_FILES=$(git status --short | wc -l | tr -d ' ')
    CURRENT_DATE=$(date +"%Y-%m-%d %H:%M")
    COMMIT_MSG="Update $CHANGED_FILES files - $CURRENT_DATE"
    echo -e "\n${BLUE}💬 Auto-generated message:${NC} $COMMIT_MSG"
else
    COMMIT_MSG="$1"
    echo -e "\n${BLUE}💬 Using provided message:${NC} $COMMIT_MSG"
fi

# Ask for confirmation
read -p "$(echo -e ${GREEN}Continue with push? [y/N]: ${NC})" -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${RED}❌ Aborted${NC}"
    exit 1
fi

# Add all changes
echo -e "\n${BLUE}📦 Adding files...${NC}"
git add -A

# Commit
echo -e "${BLUE}💾 Committing...${NC}"
git commit -m "$COMMIT_MSG"

# Push
echo -e "${BLUE}🚀 Pushing to remote...${NC}"
git push

echo -e "\n${GREEN}✅ Successfully pushed to remote!${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
