#!/usr/bin/env bash
#
# release.sh — tag a new release of the plan-sourdough-bake skill.
#
# Shows the latest release tag and the commits since then, suggests the next
# semantic version (pre-filled, editable), runs the unit tests, then creates an
# annotated tag vX.Y.Z on main and pushes it. The push triggers
# .github/workflows/release.yml, which builds the zip and publishes the release.
#
# Suggested bump, from the commits since the last tag:
#   "BREAKING" anywhere in a commit message          → major
#   a subject starting with "add" or "remove"        → minor
#   anything else                                    → patch
# Run with --help for the options.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

REMOTE=origin
BRANCH=main

usage() {
  cat <<USAGE
Usage: ./release.sh [options]

Tags and pushes a new release version (vX.Y.Z) of the current $BRANCH.

Options:
  --version X.Y.Z  use this version instead of asking (the "v" is optional)
  --yes            don't ask for confirmation
  --skip-tests     don't run the unit tests before tagging
  --dry-run        show what would happen, change nothing
  -h, --help       show this help and exit
USAGE
}

VERSION=""
ASSUME_YES=0
RUN_TESTS=1
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      [[ $# -ge 2 ]] || { echo "error: --version needs a value" >&2; exit 1; }
      VERSION="$2"; shift 2 ;;
    --yes) ASSUME_YES=1; shift ;;
    --skip-tests) RUN_TESTS=0; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "error: unknown argument '$1' (try --help)" >&2; exit 1 ;;
  esac
done

die() { echo "error: $*" >&2; exit 1; }
run() {
  if [[ $DRY_RUN -eq 1 ]]; then echo "  (dry run) $*"; else "$@"; fi
}
confirm() {  # confirm "question" → 0 for yes (default yes)
  [[ $ASSUME_YES -eq 1 ]] && return 0
  [[ -t 0 ]] || die "no terminal to ask '$1' (use --yes)"
  local answer
  read -r -p "$1 [Y/n] " answer
  [[ -z "$answer" || "$answer" =~ ^[YyJj] ]]
}

# --- preconditions ---------------------------------------------------------
git rev-parse --git-dir >/dev/null 2>&1 || die "not inside a git repository"
current=$(git symbolic-ref --short -q HEAD || true)
[[ "$current" == "$BRANCH" ]] || die "releases are tagged on $BRANCH, but you are on '${current:-a detached HEAD}'"
git diff --quiet && git diff --cached --quiet || die "the working tree has uncommitted changes; commit or stash them first"

echo "Fetching $REMOTE…"
if ! git fetch --quiet --tags "$REMOTE" "$BRANCH"; then
  echo "warning: could not fetch from $REMOTE; using the local state" >&2
fi

if upstream=$(git rev-parse -q --verify "$REMOTE/$BRANCH"); then
  read -r behind ahead < <(git rev-list --left-right --count "$upstream...HEAD")
  [[ $behind -eq 0 ]] || die "$BRANCH is $behind commit(s) behind $REMOTE/$BRANCH; pull first"
else
  ahead=0
fi

# --- latest release and the changes since ----------------------------------
latest=$(git tag -l 'v[0-9]*.[0-9]*.[0-9]*' --sort=-v:refname | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | head -n1 || true)

echo
if [[ -n "$latest" ]]; then
  echo "Latest release: $latest ($(git log -1 --format='%cs' "$latest"))"
  range="$latest..HEAD"
else
  echo "Latest release: none yet"
  range="HEAD"
fi

commits=$(git log --format='%h %s' "$range")
[[ -n "$commits" ]] || die "no commits since $latest; nothing to release"
echo
echo "Commits since ${latest:-the beginning}:"
sed 's/^/  /' <<<"$commits"

# --- suggest the next version ----------------------------------------------
if [[ -z "$latest" ]]; then
  suggestion="v1.0.0"; reason="first release"
else
  IFS=. read -r major minor patch <<<"${latest#v}"
  if git log --format='%B' "$range" | grep -q 'BREAKING'; then
    suggestion="v$((major + 1)).0.0"; reason="major: a commit says BREAKING"
  elif git log --format='%s' "$range" | grep -qiE '^(add|remove)\b'; then
    suggestion="v$major.$((minor + 1)).0"; reason="minor: features added or removed"
  else
    suggestion="v$major.$minor.$((patch + 1))"; reason="patch: fixes and changes only"
  fi
fi

echo
echo "Suggested version: $suggestion ($reason)"
if [[ -z "$VERSION" ]]; then
  if [[ -t 0 && $ASSUME_YES -eq 0 ]]; then
    read -r -e -i "$suggestion" -p "Version to release: " VERSION
  else
    VERSION="$suggestion"
  fi
fi

VERSION="v${VERSION#v}"
[[ "$VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "'$VERSION' is not a version like v1.2.3"
git rev-parse -q --verify "refs/tags/$VERSION" >/dev/null && die "tag $VERSION already exists"
if [[ -n "$latest" ]]; then
  highest=$(printf '%s\n%s\n' "$latest" "$VERSION" | sort -V | tail -n1)
  [[ "$highest" == "$VERSION" ]] || die "$VERSION is lower than the latest release $latest"
fi

# --- tests -----------------------------------------------------------------
if [[ $RUN_TESTS -eq 1 ]]; then
  echo
  echo "Running unit tests…"
  python3 -m unittest discover -q tests || die "tests failed; not tagging (use --skip-tests to override)"
fi

# --- tag and push ----------------------------------------------------------
echo
if [[ $ahead -gt 0 ]]; then
  echo "$BRANCH has $ahead commit(s) that are not on $REMOTE yet; they are pushed first."
fi
confirm "Tag $(git rev-parse --short HEAD) as $VERSION and push it to $REMOTE?" || { echo "Aborted."; exit 1; }

if [[ $ahead -gt 0 ]]; then
  run git push "$REMOTE" "$BRANCH"
fi
run git tag -a "$VERSION" -m "$VERSION"
run git push "$REMOTE" "$VERSION"

url=$(git remote get-url "$REMOTE" | sed -E 's#^git@github.com:#https://github.com/#; s#\.git$##')
echo
if [[ $DRY_RUN -eq 1 ]]; then
  echo "Dry run: nothing was tagged or pushed."
  exit 0
fi
echo "Released $VERSION. The release workflow builds the zip and publishes it:"
echo "  $url/actions/workflows/release.yml"
echo "  $url/releases/tag/$VERSION"
