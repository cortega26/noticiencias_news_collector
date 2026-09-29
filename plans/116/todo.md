# Todo: plan 116 — per-host pacing for article enrichment

- [ ] Step 0: drift check + green baseline
- [ ] Step 1: measure per-host article-fetch volume and 403/429 counts
- [ ] Step 2: implement per-host pacing + config knobs + docs
- [ ] Step 3: unit tests (same-host wait, cross-host independence, cap, release-on-failure)
- [ ] Step 4: re-measure + run the full gate
- [ ] Step 5: implementation record + ledger row update
