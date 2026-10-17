# DID swing 3: lane 6178, model cascade (base 1561385)
- **graphs/lane.md, Model routing:** replaced with "the cascade". Four tiers and a Claude Code row (haiku, sonnet, opus, fable); another tool adds its own row; an unavailable tier means the next tier up. It covers builder (lean light, one-line reason), reviewer (one tier above the builder, never below mid, top stays top), escalation (up one tier after a failed review, never lowered in a lane) and top tier (operator's yes first, marked as a hub-authored default for cost).
- **Receipt:** `builder=<tier/model> reviewer=<tier/model> reason=<one line>` on every builder and reviewer dispatch line, plus the swing and tier record at landing, with the classifier sentence. "A line missing a value is a breach" is kept from the old text, and so is the operator's named model winning. The exact-repair sentence is unchanged.
- **Other model mentions:** the scribe at :16 and :234 now reads "light tier (Haiku)". `.claude/skills/check-prs/SKILL.md:76` ("a reviewer never runs on Haiku") is still true under the cascade, and was not edited because it is out of scope.
- **Not verified:** "fable" as the top-tier alias came from the order; I did not check it.
- **ONBOARDING.md:** new step 5, "Which models do the work": run the hub on a mid-range, reasonably strong model at medium effort; the lane picks the helpers' models. The old steps 5 and 6 are now 6 and 7, and the marker text says "end of step 7".
- `python3 scripts/test_graph_pointers.py`: `ok`. `python3 scripts/test_contract_sync.py`: `OK`.
- `python3 scripts/run_tests.py`: `38 suites: 38 pass, 0 fail, 0 skip (9 tests skipped inside 4 passing suites)`.
- **Untouched:** every other file.
