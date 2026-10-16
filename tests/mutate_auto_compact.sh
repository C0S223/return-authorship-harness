#!/bin/bash
# Each mutation removes one guard the review said was uncovered. Every one must
# turn the suite RED. A mutation that stays green means the case proves nothing.
cd "$(dirname "$0")/.." || exit 1
# AC_SRC lets a lane point the battery at a working copy (mirrors AC_DIR in the suite).
# Read the installed scripts; run() mutates only its per-run scratch copies.
SRC="${AC_SRC:-.claude/hooks/auto-compact}"
# Per-run scratch dir. A fixed tmp/m let two concurrent batteries cross-write:
# one run's pristine cp landed on the other's mutant, the mutation vanished, the
# suite passed, and the guard was reported as unpinned.
mkdir -p tmp || exit 1
M="$(mktemp -d tmp/m.XXXXXX)" || exit 1
trap 'rm -rf "$M"' EXIT
# Anchor miss and surviving mutant both set this. The battery exits non-zero on
# either, so a caller that only reads the exit code cannot be told a lie.
RC=0
# MUTATE_ANCHORS_ONLY=1 applies and verifies every mutation but skips the
# ~30s suite run per mutation, so the anchor half is cheap enough to run from
# scripts/run_tests.py (tests/test_mutation_anchors.py) inside its
# 120s per-suite budget. The full battery is still the thing to run when the
# suite or the guards move.
ANCHORS_ONLY="${MUTATE_ANCHORS_ONLY:-}"
run() {
  local name="$1"; shift
  rm -rf "$M" && mkdir -p "$M" && cp "$SRC"/check.sh "$SRC"/resume.sh "$M"/
  "$@" || { echo "MISS  $name -- mutation command failed: $*"; RC=1; return; }
  if cmp -s "$SRC/check.sh" "$M"/check.sh && cmp -s "$SRC/resume.sh" "$M"/resume.sh; then
    echo "MISS  $name -- anchor not found: $*"; RC=1; return
  fi
  if [ -n "$ANCHORS_ONLY" ]; then echo "anchor $name -- still matches"; return; fi
  if AC_DIR="$M" bash tests/test_auto_compact.sh >/dev/null 2>&1; then
    RC=1; echo "BAD   $name — suite still PASSES"
  else
    echo "ok    $name — turns the suite red"
  fi
}

run "S1 trap in check.sh"   sed -i "/^trap 'exit 0' ERR$/d" "$M"/check.sh
run "S1 trap in resume.sh"  sed -i "/^trap 'exit 0' ERR$/d" "$M"/resume.sh
run "S2 full path frame"    sed -i 's@HANDOFF="\$REL/\$(basename@HANDOFF="$(basename@' "$M"/resume.sh
run "S3 root validation"    sed -i 's@\[ -f "\$c/CLAUDE.md" \]@[ -n "$c" ]@' "$M"/resume.sh
run "S4 re-arm clears both" sed -i "s@'del(.\[\$s\])'@'.[\$s] |= del(.nudged)'@" "$M"/check.sh
run "S5 input_tokens term"  sed -i 's@\[.input_tokens, .cache_creation_input_tokens@[.cache_creation_input_tokens@' "$M"/check.sh
run "S5 cache_read term"    sed -i 's@, .cache_read_input_tokens\]@]@' "$M"/check.sh
run "S6 numeric coercion"   sed -i 's@| map(numbers) | add // 0@| (.[0] // 0) + (.[1] // 0) + (.[2] // 0)@' "$M"/check.sh
run "S7 base-10 forcing"    sed -i 's@CEILING=\$(( 10#\$CEILING ))@CEILING=$(( CEILING ))@' "$M"/check.sh
run "S8 sidechain filter"   sed -i 's@| select(.isSidechain != true)@@' "$M"/check.sh
run "S10 runbook path"      sed -i 's@RUNBOOK="docs/auto-compact-runbook.md"@RUNBOOK="does/not/exist.md"@' "$M"/check.sh
run "F7 source guard"       sed -i '/^\[ "\$SOURCE" = "compact" \] || exit 0$/d' "$M"/resume.sh
run "delegate gate"         sed -i '/has("agent_id")/,+2d' "$M"/check.sh
run "compact_boundary"      sed -i 's@/"subtype":"compact_boundary"/ { keep=""; next }@@' "$M"/check.sh
run "clamp"                 sed -i 's@\[ "\$CEILING" -ge 100000 \] || CEILING=350000@:@' "$M"/check.sh
exit $RC
