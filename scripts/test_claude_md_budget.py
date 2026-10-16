#!/usr/bin/env python3
"""CLAUDE.md and its enforcement reference share a size budget.

WHY THIS EXISTS. In the v1 tree (AI2) rules were added to the contract and
never taken away, so the file grew without bound. Nothing measured it, so
nothing objected. §6 now carries the rule -- a new rule is dense and names its
failure and its reader -- and this file is the half that makes growth loud
instead of silent.

WHAT TO DO WHEN IT FAILS. The failure is not "raise the number". Cut or tighten
something, or state why nothing can go and raise CEILING deliberately in the
same commit that adds the text. Raising it quietly is the exact failure this guards.

WHY A TEST AND NOT A HOOK. §8 line 80 closes the hook set: an addition names
its incident and either retires a hook or raises the budget. A byte check in
`policy-mutate.py` would have been a budget raise on a permission gate, which
is a different job than that gate does. This runs in the existing suite
instead, costs one file, and blocks nothing -- the operator lands the edit and
sees the suite go red, which is the right order for a file only humans unlock.

# ponytail: bytes, not an AST or a section-by-section budget. The failure mode
# is a file that grows; one number catches it. Per-section budgets when a
# section grows while the total holds, and not before.
"""
import re
import sys
from pathlib import Path

# Measured 2026-08-31 after the density trim: 14,406 bytes / 2,062 words, down
# 14.4% from 16,823. The ceiling sits ~4% above that -- room for a genuine new
# rule, not room for a paragraph of narrative.
CEILING = 15_000
# Sections the tree cites by number; §7 is retired on purpose (contract-redesign `review.md`, adoption step 7).
SECTIONS = ("0", "1", "2", "3", "4", "5", "6", "8", "9")

TARGET = Path(__file__).resolve().parents[1] / "CLAUDE.md"
ENFORCEMENT = TARGET.parent / "docs/enforcement/CLAUDE.md"


def test_contract_stays_within_budget():
    assert TARGET.is_file(), f"{TARGET} is missing -- the contract is the thing being guarded"
    assert ENFORCEMENT.is_file(), f"{ENFORCEMENT} is missing -- root section 8 requires it"
    root_size = TARGET.stat().st_size
    size = root_size + ENFORCEMENT.stat().st_size
    assert size <= CEILING, (
        f"Contract + enforcement total {size:,} bytes, over the {CEILING:,} ceiling by {size - CEILING:,}.\n"
        "        Per §6: name the sentence this edit retires, or state why none exists\n"
        "        and raise CEILING in the same commit. Do not raise it quietly."
    )
    # The opposite failure is silent too: a truncating write or a bad merge
    # leaves a SMALL file that a ceiling-only check calls a pass. A byte floor
    # also failed legitimate trims (contract-redesign `review.md`, adoption step 7), so check the numbered sections.
    headings = set(re.findall(r"^## (\d+)\.", TARGET.read_text(encoding="utf-8"), re.M))
    missing = [s for s in SECTIONS if s not in headings]
    assert not missing, (
        f"CLAUDE.md is missing section(s) {missing} ({root_size:,} bytes) -- "
        "content was lost, not trimmed. Check the last write."
    )


def test_the_budget_rule_is_actually_stated_in_the_file():
    # The number is enforced here; the pointer lives in §6. A guard the
    # contract does not name is one nobody will look up.
    text = TARGET.read_text(encoding="utf-8")
    assert Path(__file__).name in text, (
        f"§6 no longer points at {Path(__file__).name}. Write implies read (§6): "
        "a guard the contract does not name is one nobody will look up."
    )


if __name__ == "__main__":
    # Auto-discover, per an earlier fix: a hand-listed call block silently skips any
    # test not added to it.
    for _name, _fn in sorted(dict(globals()).items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("ok")
