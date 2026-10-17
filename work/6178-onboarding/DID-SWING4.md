# DID swing 4: lane 6178, time bucket (base d254f63)
- **graphs/lane.md step 1:** the work-order list gains a 2-line item, "estimated human time", as one bucket of `<15 min`, `15 min-1 h`, `1-4 h` or `>4 h` (the SWE-bench Verified buckets), rounding up when unsure because human estimates run optimistic.
- **Cascade:** the builder's reason cites the time bucket. A declined top-tier dispatch runs on heavy, and its reason starts `top declined`; both are marked as hub-authored defaults. The landing record now holds the bucket next to the swings and tiers, and the classifier sentence says the bucket is part of the data.
- **Not verified:** the bucket names, and the claim that human estimates run optimistic, came from the order; I did not check them against a source.
- **ONBOARDING.md step 3:** one clause added: each work order guesses how long a person would take, and that guess helps pick the model.
- `python3 scripts/run_tests.py`: `38 suites: 38 pass, 0 fail, 0 skip (9 tests skipped inside 4 passing suites)`.
- **Untouched:** every other file.
