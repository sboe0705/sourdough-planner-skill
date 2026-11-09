#!/usr/bin/env bash
#
# install.sh — make the plan-sourdough-bake skill available to your AI agent.
#
# By default symlinks the skill folder into Claude Code's personal skills
# directory (~/.claude/skills), so a `git pull` here updates the installed
# skill too. Run with --help for the options.
#
set -euo pipefail

SKILL_NAME="plan-sourdough-bake"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$SCRIPT_DIR/$SKILL_NAME"

usage() {
  cat <<USAGE
Usage: ./install.sh [options]

Symlinks the $SKILL_NAME skill into your agent's skills directory.

Options:
  --project DIR   install into DIR/.claude/skills (one project only)
                  instead of ~/.claude/skills (all your projects)
  --target DIR    install into any skills directory DIR (other agents)
  --copy          copy the files instead of symlinking them
  --force         replace an existing $SKILL_NAME entry in the target
  --uninstall     remove the installed skill from the target
  -h, --help      show this help and exit

Examples:
  ./install.sh                          # ~/.claude/skills/$SKILL_NAME -> this repo
  ./install.sh --project ~/code/bakery  # ~/code/bakery/.claude/skills/$SKILL_NAME
  ./install.sh --uninstall
USAGE
}

TARGET_DIR="${HOME}/.claude/skills"
MODE="link"
FORCE=0
UNINSTALL=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)
      [[ $# -ge 2 ]] || { echo "error: --project needs a directory" >&2; exit 1; }
      TARGET_DIR="${2%/}/.claude/skills"; shift 2 ;;
    --target)
      [[ $# -ge 2 ]] || { echo "error: --target needs a directory" >&2; exit 1; }
      TARGET_DIR="${2%/}"; shift 2 ;;
    --copy) MODE="copy"; shift ;;
    --force) FORCE=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "error: unknown argument '$1' (try --help)" >&2; exit 1 ;;
  esac
done

if [[ ! -f "$SOURCE/SKILL.md" ]]; then
  echo "error: $SOURCE/SKILL.md not found — run this script from the repository" >&2
  exit 1
fi

DEST="$TARGET_DIR/$SKILL_NAME"

# Is DEST a symlink that already points at this repository's skill folder?
points_here() {
  [[ -L "$DEST" ]] && [[ "$(cd "$DEST" 2>/dev/null && pwd -P)" == "$(cd "$SOURCE" && pwd -P)" ]]
}

if [[ $UNINSTALL -eq 1 ]]; then
  if [[ ! -e "$DEST" && ! -L "$DEST" ]]; then
    echo "Nothing to remove: $DEST does not exist."
    exit 0
  fi
  if [[ -L "$DEST" ]]; then
    rm "$DEST"
  elif [[ -f "$DEST/SKILL.md" ]] && grep -q "^name: $SKILL_NAME\$" "$DEST/SKILL.md"; then
    rm -r "$DEST"   # a copy made with --copy
  else
    echo "error: $DEST is not an installation of $SKILL_NAME — leaving it alone" >&2
    exit 1
  fi
  echo "Removed $DEST"
  exit 0
fi

if points_here && [[ $MODE == "link" ]]; then
  echo "Already installed: $DEST -> $SOURCE"
  exit 0
fi

if [[ -e "$DEST" || -L "$DEST" ]]; then
  if [[ $FORCE -ne 1 ]]; then
    echo "error: $DEST already exists. Use --force to replace it, or --uninstall first." >&2
    exit 1
  fi
  if [[ -L "$DEST" || -f "$DEST" ]]; then rm "$DEST"; else rm -r "$DEST"; fi
fi

mkdir -p "$TARGET_DIR"
if [[ $MODE == "copy" ]]; then
  cp -R "$SOURCE" "$DEST"
  cp "$SCRIPT_DIR/LICENSE" "$DEST/LICENSE"
  find "$DEST" -name __pycache__ -type d -prune -exec rm -rf {} +
  echo "Copied $SKILL_NAME to $DEST"
else
  ln -s "$SOURCE" "$DEST"
  echo "Linked $DEST -> $SOURCE"
fi

if [[ "$TARGET_DIR" == *"/.claude/skills" ]]; then
  echo "Start a new Claude Code session and use /$SKILL_NAME, or just share a bread recipe."
fi
