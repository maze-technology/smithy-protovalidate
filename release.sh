#!/bin/bash
set -euo pipefail

# === Config ===
BASE_BRANCH="main"
SOURCE_BRANCH="develop"

# Store original branch
ORIGINAL_BRANCH=$(git symbolic-ref --short HEAD)

# Get repo info from git remote
REPO_URL=$(git config --get remote.origin.url)

# Extract owner/repo from HTTPS or SSH format
if [[ "$REPO_URL" =~ github\.com[:/](.+/.+?)(\.git)?$ ]]; then
  REPO="${BASH_REMATCH[1]}"
else
  echo "❌ Unable to parse repository from remote URL: $REPO_URL"
  exit 1
fi

echo "📦 Repository: $REPO"
echo "🚀 Preparing to fast-forward $BASE_BRANCH from $SOURCE_BRANCH"

# === Sync and check out base branch ===
git fetch origin

# Update SOURCE_BRANCH to match remote
echo "📥 Updating $SOURCE_BRANCH to match remote..."
git checkout $SOURCE_BRANCH
git reset --hard origin/$SOURCE_BRANCH

git checkout $BASE_BRANCH
git reset --hard origin/$BASE_BRANCH

# === Attempt fast-forward merge ===
if git merge-base --is-ancestor origin/$SOURCE_BRANCH $BASE_BRANCH; then
  echo "✅ $BASE_BRANCH is already up-to-date with $SOURCE_BRANCH"
else
  echo "🔁 Merging changes..."
  git merge --ff-only origin/$SOURCE_BRANCH
  git push origin $BASE_BRANCH
  echo "✅ Successfully fast-forwarded $BASE_BRANCH from $SOURCE_BRANCH"
fi

# Return to original branch
git checkout $ORIGINAL_BRANCH
