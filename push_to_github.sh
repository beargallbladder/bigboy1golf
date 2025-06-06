#!/bin/bash

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}🚀 GitHub Push Helper${NC}"
echo ""
echo -e "${YELLOW}Enter your GitHub repository URL:${NC}"
echo "Example: https://github.com/YOUR-USERNAME/golf-shot-tracker.git"
read -p "> " REPO_URL

if [[ -z "$REPO_URL" ]]; then
    echo -e "${YELLOW}No URL provided. Exiting.${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}Adding remote origin...${NC}"
git remote add origin "$REPO_URL" 2>/dev/null || {
    echo -e "${YELLOW}Remote already exists. Updating URL...${NC}"
    git remote set-url origin "$REPO_URL"
}

echo -e "${GREEN}Pushing to GitHub...${NC}"
git push -u origin main

echo ""
echo -e "${BLUE}✅ Success! Your code is now on GitHub${NC}"
echo -e "${BLUE}Repository URL: $REPO_URL${NC}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Go to render.com"
echo "2. Connect this repository"
echo "3. Follow the deployment steps in README.md" 