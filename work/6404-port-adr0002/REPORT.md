# Report: lane 6404, swing 1 (hub as builder)

Candidate 7a84b54 on base c26fb2d: APPENDIX A applied with `git apply`, APPENDIX B written to
`docs/adr/0002-lift-unruled-settings-denies.md`. Nothing else authored.

**Hub departure, mechanical.** The patch arrived with its eleven hunk headers written in fullwidth
`＠＠` instead of `@@`, which `git apply` cannot read. The hub replaced only those characters
(`sed 's/＠＠/@@/g'`; a diff of the two copies shows no other change). The resulting blobs prove it:
six of the eight patched files hash to the patch's own index lines (f19559a twice, c90059f,
ff1e77f, d4ddbf8, 5cb22f3), and the two scripts hash to fadc40c and a87adc9, as the order
expected (their index lines e4f70c1 and ab6a817 predate the scrub of one comment line each).

**Acceptance checks, run on the candidate.**
a. `git hash-object CLAUDE.md` → f19559a78a499312d979e489a26a078ea54b254e; `cmp CLAUDE.md AGENTS.md` → no output, exit 0.
b. deny count → 18.
c. scrub grep over the nine files' base-to-HEAD diff → no output, exit 1.
d. `python3 scripts/run_tests.py` → `40 suites: 40 pass, 0 fail, 0 skip (9 tests skipped inside 4 passing suites)`.

Falsifier for the prose part, which admits no failing test: the adversarial review.
