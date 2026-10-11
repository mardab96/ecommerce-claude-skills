# Changelog

## [Unreleased]

### Fixed

- Shipping recovery averages the two middle order values for an even-sized
  sample instead of reporting the upper middle value. Regression cases cover
  even, odd, single, decimal and repeated values.

## [2.3.0] - 2026-07-27

Second QA round. The graders ran the scripts against their own fixtures instead
of reading them, which found seven defects the first round's reading had missed.

### Fixed

- `margin_stack.py` charged a fixed per-transaction fee once per UNIT, so every
  multi-unit basket had its fees overstated and its margin understated. It now
  uses an orders column when the export has one, accepts `--units-per-order` when
  it does not, and says which it used.
- `margin_stack.py` printed a clean margin percentage and breakeven ROAS even
  when COGS was absent entirely, producing figures like "100% margin" with the
  caveat parked in a separate column. Those derived figures are now withheld,
  because a percentage computed without product cost is not a margin.
- `catalog_scan.py` took the first row's image count when collapsing Shopify
  variant rows, so a product with eight images reported one and was flagged as
  having an image gap. It now takes the highest count and the longest
  description, which is what the docstring had claimed all along.
- `promo_impact.py` overwrote its coverage warning each time it found one, so a
  missing baseline vanished from the output while the uplift built on it was
  still printed. Warnings now accumulate.
- `subscription_survival.py` classified a `trialing` subscriber as a voluntary
  cancellation, corrupting the involuntary share that the whole analysis turns
  on. Non-terminal statuses are recognised, and nobody who never completed a
  cycle can be counted as having churned out of one.
- `shipping_recovery.py` counted refund rows with negative order values in the
  overall total while excluding them from every band, so the two disagreed with
  no explanation. They are now excluded from both and reported separately.
- `cohort_read.py` carried a dead `if False` branch in its date parser.

### Added

- `scripts/selftest.py`. Twenty regression checks, one per defect that actually
  shipped in this pack, so none of them can come back quietly. The pack claims
  these scripts do not produce confidently wrong numbers; this file is what that
  claim is worth.
- `scripts/dispute_rate.py`. The pack had asserted that the skills without
  scripts were classification rather than counting, and Chargeback and Fraud
  Pattern Review was a clear counterexample: it computes a rate over time against
  a denominator that is easy to get wrong. The claim is now true rather than
  argued.

### Changed

- The closing sentence of every `Decision and evidence standard` section was
  identical across ten skills. It now lives once in
  `references/output-standard.md`, and each skill states only its own ranking
  rule.
- The six script steps shared one rhetorical cadence. Varied, because a reader
  who can predict the next skill from the last two stops reading.

## [2.2.0] - 2026-07-27

Fixes from an independent QA pass by four graders, two reading as the target
persona and two auditing craft. The pack scored below its own bar on both axes;
these are the findings that survived verification.

### Fixed

- **The documented install broke the scripts it advertised.** `cp -r *ecommerce*`
  copied the skill folders and neither `scripts/` nor `references/`, which ten
  skills reach for by relative path. Shared paths are now `../scripts/` and
  `../references/`, which resolve both inside the repo and after install, and the
  install command copies all three. The previous install check counted folders
  and passed while this was broken.
- **`margin_stack.py` added negative discounts back to revenue.** Exports that
  encode discounts and returns as negative numbers inflated CM2 and CM3 silently.
  Magnitudes are now used whatever sign the export chose, and the script says
  when it had to.
- **`cohort_read.py` blanked a whole segment for one recent customer.** Maturity
  was gated per group, so a channel with 500 mature customers reported nothing
  because one signed up yesterday, which made the payback comparison the script
  exists for impossible. Maturity is now per customer, and the count behind each
  horizon is printed next to its value.
- **`catalog_scan.py` counted Shopify variant rows as products.** A native
  product export writes one row per variant with the description only on the
  first, so continuation rows inflated the product count and every one read as an
  empty description. Rows are collapsed per handle before anything is counted.

### Added

- `scripts/promo_impact.py`, `scripts/shipping_recovery.py` and
  `scripts/subscription_survival.py`. Arithmetic rigour was applied to three
  skills and skipped on three others that needed it just as much, which undercut
  the claim everywhere it was absent.
- `references/getting-your-data.md`. Assembling the export, not the analysis, is
  the real bottleneck for a small team, and the pack previously offered nothing
  on it.
- A "what you can run today" table in the README, ordering all 20 skills by how
  hard they are to feed rather than by number.
- A platform-native first step in Subscription Churn Review: pull Recharge, Skio,
  Stay AI or Shopify's own reporting before re-deriving survival from an export.

### Changed

- The nine skills that left `### Missing data` as an empty heading now say what
  is missing and why it matters for that specific analysis.
- The scoring sentence and the approval guardrail, which had been near-identical
  across ten skills, now carry each skill's own ranking rule and its own
  irreversible action. A reader who has seen two skills should not be able to
  predict the rest.

## [2.1.0] - 2026-07-27

Quality pass on the 2.0.0 expansion, applied after the pack's own QA gate was
run properly rather than skipped.

### Added

- `scripts/margin_stack.py`, `scripts/cohort_read.py`, `scripts/catalog_scan.py`
  plus `scripts/README.md`. The three arithmetic-heavy skills no longer ask the
  model to do the counting by eye.
- `scripts/validate-skills.py`. Checks every `SKILL.md` for required sections,
  an activation phrase, workflow depth and placeholder text.
- Demo outputs for skills 11-20 in `examples/demo-outputs.md`.
- `AGENTS.md` covering how the pack composes and where its judgement shifts by
  vertical.
- MIT `LICENSE`. The README claimed the licence for two months without the file.

### Changed

- Activation phrases fixed on Launch Readiness Check, Promo and Discount Impact
  Review and Subscription Churn Review. Their descriptions had no "Use when"
  clause, so they were less likely to trigger when they should.
- Scope stated honestly on the three skills with an input-availability risk.
  Subscription Churn Review now says it only applies to recurring-billing
  stores, AI Shopping Readiness says it needs rendered HTML rather than a URL,
  and Onsite Search and Merchandising Review says it needs search logging
  switched on and makes that the first recommendation when it is not.
- Catalog Content Audit gained a scale rule as step 0: above roughly 150 SKUs
  the counting goes through the script, because a sampled read reported as a
  full audit is the failure mode this skill would otherwise ship.

## [2.0.0] - 2026-07-27

### Added

Skills 11-20. The first ten all diagnosed the storefront; these cover the
economics underneath it and the store as machine-readable data.

- 11 Contribution Margin Check
- 12 Promo and Discount Impact Review
- 13 Shipping Economics Review
- 14 LTV and Cohort Read
- 15 Subscription Churn Review
- 16 Catalog Content Audit
- 17 AI Shopping Readiness
- 18 Chargeback and Fraud Pattern Review
- 19 Onsite Search and Merchandising Review
- 20 Launch Readiness Check

Nine evidence tags and five failure modes added to `references/output-standard.md`,
ten copy-paste prompts, six owner playbooks.

### Changed

- Install command now creates the skills directory and copies only skill
  folders, so a fresh clone installs 20 folders and nothing else.

## [1.1.0] - 2026-06-01

Examples, playbooks, synthetic demo outputs, output standard, and per-skill
evidence tagging and scoring.

## [1.0.0] - 2026-06-01

Initial pack of 10 skills.
