#!/usr/bin/env bash
# Fails the build if GPU/CUDA packages resolve into the dependency tree.
#
# This project is CPU-only by design. CUDA never arrives directly — it arrives
# transitively via torch, which is pulled in by sentence-transformers,
# transformers, langchain-huggingface or unstructured. That is ~2.5GB of wheels
# this project will never execute.
#
# Run locally, in CI, and as a Docker build step so a dependency added months
# from now regresses loudly instead of silently.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="$REPO_ROOT/apps/api"

# Package names that must never appear in the resolved tree.
BANNED_INSTALLED='^(nvidia[-_].*|triton|cuda.*|.*[-_]cu[0-9]{2,3}|torch|torchvision|torchaudio|sentence[-_]transformers|transformers|unstructured)$'
# Names that must never appear in a dependency declaration.
BANNED_DECLARED='(^|[^a-z0-9_-])(torch|torchvision|torchaudio|sentence-transformers|transformers|unstructured|nvidia-[a-z0-9-]+|triton)([^a-z0-9_.-]|$)'

fail() {
  echo "ERROR: $1" >&2
  echo "       This project is CPU-only. See the CPU-only constraint in README.md." >&2
  exit 1
}

# --- 1. Installed packages -----------------------------------------------------
# Prefer uv; fall back to the venv's pip; skip if no environment exists yet
# (a fresh clone in CI checks declarations only).
list_installed() {
  # uv on PATH, else the project-local tools venv.
  local uv_bin=""
  if command -v uv >/dev/null 2>&1; then
    uv_bin="$(command -v uv)"
  elif [ -x "$REPO_ROOT/.tools/uv-venv/bin/uv" ]; then
    uv_bin="$REPO_ROOT/.tools/uv-venv/bin/uv"
  fi

  if [ -n "$uv_bin" ] && [ -d "$API_DIR/.venv" ]; then
    (cd "$API_DIR" && VIRTUAL_ENV="$API_DIR/.venv" "$uv_bin" pip list --format=json 2>/dev/null) && return 0
  fi

  # No uv, or no venv: ask the interpreter itself. uv-created venvs have no pip,
  # so go through importlib.metadata rather than `pip list`.
  if [ -x "$API_DIR/.venv/bin/python" ]; then
    "$API_DIR/.venv/bin/python" - <<'PY' 2>/dev/null && return 0
import json
from importlib.metadata import distributions
print(json.dumps([{"name": d.metadata["Name"] or ""} for d in distributions()]))
PY
  fi
  return 1
}

if installed_json="$(list_installed)"; then
  # One package name per line, lowercased, underscores normalised to hyphens.
  installed_names="$(printf '%s' "$installed_json" \
    | grep -o '"name": *"[^"]*"' \
    | sed 's/.*"name": *"//; s/"$//' \
    | tr '[:upper:]' '[:lower:]' \
    | tr '_' '-')" || installed_names=""

  if hits="$(printf '%s\n' "$installed_names" | grep -Ei "$BANNED_INSTALLED" || true)" && [ -n "$hits" ]; then
    echo "Offending installed packages:" >&2
    printf '  %s\n' $hits >&2
    fail "GPU/CUDA packages resolved into the installed environment."
  fi
  echo "OK: installed environment is CPU-only ($(printf '%s\n' "$installed_names" | grep -c . ) packages)."
else
  echo "NOTE: no Python environment found at apps/api/.venv — checking declarations only."
fi

# --- 2. Declared dependencies --------------------------------------------------
# Catches a banned package added to pyproject/lock before anyone installs it.
for f in "$API_DIR/pyproject.toml" "$API_DIR/uv.lock" "$API_DIR/requirements.txt"; do
  [ -f "$f" ] || continue
  # Strip comments first — this file documents the banned list, and saying the
  # names out loud in a comment must not fail the check.
  if hits="$(sed 's/#.*//' "$f" | grep -Ein "$BANNED_DECLARED" || true)" && [ -n "$hits" ]; then
    echo "Offending lines in ${f#"$REPO_ROOT/"}:" >&2
    printf '  %s\n' "$hits" >&2
    fail "A banned GPU-adjacent dependency is declared."
  fi
done

echo "OK: CPU-only dependency tree."
