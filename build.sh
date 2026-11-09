#!/usr/bin/env bash
#
# build.sh — package the plan-sourdough-bake skill as a zip for upload to
# Claude.ai / Claude Desktop (Settings → Capabilities → Skills) or any other
# agent that imports Agent Skills as a zip.
#
# Checks the SKILL.md frontmatter, runs the unit tests, and writes
# dist/plan-sourdough-bake.zip with the skill folder at the zip's root.
# Caches (__pycache__, *.pyc) and OS junk are left out. The zip is
# reproducible: the same sources always give byte-identical output.
# Run with --help for the options.
#
set -euo pipefail

SKILL_NAME="plan-sourdough-bake"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$SCRIPT_DIR/$SKILL_NAME"

usage() {
  cat <<USAGE
Usage: ./build.sh [options]

Packages the $SKILL_NAME skill as an uploadable zip.

Options:
  --output FILE   write the zip to FILE instead of dist/$SKILL_NAME.zip
  --skip-tests    don't run the unit tests before packaging
  -h, --help      show this help and exit
USAGE
}

OUTPUT="$SCRIPT_DIR/dist/$SKILL_NAME.zip"
RUN_TESTS=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output)
      [[ $# -ge 2 ]] || { echo "error: --output needs a file name" >&2; exit 1; }
      OUTPUT="$2"; shift 2 ;;
    --skip-tests) RUN_TESTS=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "error: unknown argument '$1' (try --help)" >&2; exit 1 ;;
  esac
done

if [[ ! -f "$SOURCE/SKILL.md" ]]; then
  echo "error: $SOURCE/SKILL.md not found — run this script from the repository" >&2
  exit 1
fi
command -v python3 >/dev/null || { echo "error: python3 is required" >&2; exit 1; }

if [[ $RUN_TESTS -eq 1 ]]; then
  echo "Running unit tests…"
  (cd "$SCRIPT_DIR" && python3 -m unittest discover -q tests) || {
    echo "error: tests failed — not packaging (use --skip-tests to override)" >&2
    exit 1
  }
fi

mkdir -p "$(dirname "$OUTPUT")"

if [[ ! -f "$SCRIPT_DIR/LICENSE" ]]; then
  echo "error: LICENSE not found next to build.sh" >&2
  exit 1
fi

python3 -I - "$SOURCE" "$SKILL_NAME" "$OUTPUT" "$SCRIPT_DIR/LICENSE" <<'PY'
import os, re, sys, zipfile

source, skill_name, output, license_path = sys.argv[1:5]

# --- validate the SKILL.md frontmatter -------------------------------------
with open(os.path.join(source, "SKILL.md"), encoding="utf-8") as f:
    text = f.read()
m = re.match(r"---\r?\n(.*?)\r?\n---\r?\n", text, re.S)
if not m:
    sys.exit("error: SKILL.md has no YAML frontmatter")
fields = {}
for line in m.group(1).splitlines():
    km = re.match(r"([A-Za-z_-]+):\s*(.*)$", line)
    if km:
        fields[km.group(1)] = km.group(2).strip().strip("'\"")

errors = []
name = fields.get("name", "")
desc = fields.get("description", "")
if name != skill_name:
    errors.append(f"name is {name!r}, expected {skill_name!r} (must match the folder)")
if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) or len(name) > 64:
    errors.append("name must be lowercase letters, digits and hyphens, at most 64 characters")
if not desc:
    errors.append("description is missing")
elif len(desc) > 1024:
    errors.append(f"description is {len(desc)} characters, the limit is 1024")
if errors:
    sys.exit("error: SKILL.md frontmatter:\n  " + "\n  ".join(errors))

# --- collect files ---------------------------------------------------------
SKIP_DIRS = {"__pycache__", ".git", ".pytest_cache"}
SKIP_FILES = {".DS_Store", "Thumbs.db"}
files = []
for root, dirs, names in os.walk(source):
    dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
    for n in sorted(names):
        if n in SKIP_FILES or n.endswith((".pyc", ".pyo")) or n.startswith("."):
            continue
        files.append(os.path.join(root, n))
# the repo-root LICENSE ships inside the skill folder (Apache-2.0 §4a)
if not os.path.exists(os.path.join(source, "LICENSE")):
    files.append(license_path)

# --- write a reproducible zip ----------------------------------------------
def arc_rel(path):
    if path == license_path:
        return "LICENSE"
    return os.path.relpath(path, source).replace(os.sep, "/")

FIXED_TIME = (1980, 1, 1, 0, 0, 0)
tmp = output + ".tmp"
with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
    for path in files:
        arc = f"{skill_name}/{arc_rel(path)}"
        info = zipfile.ZipInfo(arc, FIXED_TIME)
        info.compress_type = zipfile.ZIP_DEFLATED
        mode = 0o755 if path.endswith((".py", ".sh")) else 0o644
        info.external_attr = (0o100000 | mode) << 16
        with open(path, "rb") as f:
            z.writestr(info, f.read())
os.replace(tmp, output)

print(f"Packaged {len(files)} files:")
for path in files:
    print(f"  {skill_name}/{arc_rel(path)}")
PY

SIZE=$(du -h "$OUTPUT" | cut -f1)
echo "Wrote $OUTPUT ($SIZE)"
echo "Upload it in Claude.ai under Settings → Capabilities → Skills (code execution must be on)."
