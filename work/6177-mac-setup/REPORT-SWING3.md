# Report: lane 6177, swing 3 (candidate 8375fd9, base ee0b7a9)

**Authority.** The grant is unchanged. SE round 1 found F1 and F2, both C1, so a second round
is allowed. AR round 1 was ACCEPT with C1-C3, and this swing is its in-round close.

**What changed (DID-SWING3.md, checked against the diff).**
- SE F1: the bash>3.2 table lists 65 spellings. It catches all 18 planted lines from the
  grill, and 19 lookalikes that bash 3.2 accepts match nothing.
- SE F2: the strict-sed shim parses options the way getopt does and refuses `i` in any form.
  A planted `sed -Ei` battery now fails.
- AR C1-C3: applied to SETUP.md :71, :176-181, word for word.
- `ee0b7a9..8375fd9`: SETUP.md, tests/test_log_escape.py, tests/test_mutation_anchors.py and
  DID-SWING3.md. Nothing else.

**Hub reruns at 8375fd9.**
- Tree clean.
- `run_tests.py`: "38 suites: 38 pass, 0 fail, 0 skip".
- preflight rc 0.
- Scrub on the tree and `759372b..HEAD` history: clean.

**Left uncaught, as the builder states it:**
- a `case` later inside `$( )`;
- `read` options after an option that takes an argument;
- any construct split across lines.

**Outside the tree.** The builder's replay left 18 temp directories under the container's
/tmp, holding copies of log-escape.sh. Nothing private; the container is ephemeral.
