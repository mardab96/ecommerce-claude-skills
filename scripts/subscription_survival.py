#!/usr/bin/env python3
"""Build subscription survival by cycle, split by churn type.

Used by: subscription-churn-review-ecommerce

Why this exists: this is cohort maths wearing a different hat, and it has the
same failure mode. A single churn percentage tells you nothing, because failed
cards, deliberate cancellations and pauses that never resumed have three
different fixes. This splits them mechanically and applies the same maturity
guard the cohort script uses: a subscriber who has not had time to reach cycle 4
is not counted as having churned before it.

Input: one CSV with a row per SUBSCRIBER.

  subscriber or id       required
  status                 required (active / cancelled / paused / failed ...)
  cycles                 required, cycles completed or billed
  reason                 optional, cancellation reason
  churn_type             optional, voluntary / involuntary if your platform says

When churn_type is absent it is inferred from status and reason text: anything
mentioning payment, card, declined, dunning or failed is involuntary. That
inference is printed so it can be checked, because it is the number the whole
analysis turns on.

usage:
  python3 scripts/subscription_survival.py subscribers.csv
  python3 scripts/subscription_survival.py subscribers.csv --max-cycle 12 --json

exit 0 = ran, 2 = could not run.
"""
import argparse
import csv
import json
import re
import sys

ALIASES = {
    "subscriber": ["subscriber", "subscriber id", "id", "customer", "customer id", "email"],
    "status": ["status", "state", "subscription status"],
    "cycles": ["cycles", "cycle", "billing cycles", "orders", "cycles completed", "charge count"],
    "reason": ["reason", "cancellation reason", "cancel reason", "churn reason"],
    "churn_type": ["churn type", "churn_type", "cancellation type"],
}
INVOLUNTARY = re.compile(
    r"payment|card|declin|dunn|fail|expire|insufficient|chargeback|billing error", re.I)
PAUSED = re.compile(r"paus|skip|hold|snooz", re.I)
# Match status words, not active-looking substrings in inactive/deactivated.
ACTIVE = re.compile(r"\b(?:activ\w*|current|live|trial\w*|pending|onboard\w*|scheduled)\b", re.I)


def norm(s):
    return " ".join(str(s or "").strip().lower().replace("_", " ").split())


def to_int(raw):
    s = str(raw or "").strip()
    for ch in ", ":
        s = s.replace(ch, "")
    try:
        return int(float(s))
    except ValueError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--max-cycle", type=int, default=12)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        with open(args.csv_path, newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
    except OSError as exc:
        print("could not read %s: %s" % (args.csv_path, exc), file=sys.stderr)
        return 2
    if not rows:
        print("no rows", file=sys.stderr)
        return 2

    header = {norm(h): h for h in rows[0].keys()}
    cm = {}
    for key, aliases in ALIASES.items():
        for alias in aliases:
            if alias in header:
                cm[key] = header[alias]
                break
    missing = [k for k in ("status", "cycles") if k not in cm]
    if missing:
        print("missing required columns: %s" % ", ".join(missing), file=sys.stderr)
        print("columns found: %s" % ", ".join(rows[0].keys()), file=sys.stderr)
        return 2

    subs, skipped, inferred, never_billed = [], 0, 0, 0
    for row in rows:
        cycles = to_int(row.get(cm["cycles"]))
        status = str(row.get(cm["status"], "")).strip()
        if cycles is None or not status:
            skipped += 1
            continue
        reason = str(row.get(cm.get("reason", ""), "")) if cm.get("reason") else ""
        declared = str(row.get(cm.get("churn_type", ""), "")).strip().lower() if cm.get("churn_type") else ""

        if ACTIVE.search(status):
            kind = "active"
        elif cycles < 1:
            # Nobody who never completed a cycle can have churned out of one.
            # Counting them inflates the voluntary bucket, which is the number
            # the involuntary share is measured against.
            kind = "active"
            never_billed += 1
        elif PAUSED.search(status) or PAUSED.search(reason):
            kind = "paused"
        elif declared in ("voluntary", "involuntary"):
            kind = declared
        else:
            blob = status + " " + reason
            kind = "involuntary" if INVOLUNTARY.search(blob) else "voluntary"
            if not declared:
                inferred += 1
        subs.append({"cycles": cycles, "kind": kind, "reason": reason.strip()})

    if not subs:
        print("no usable subscriber rows", file=sys.stderr)
        return 2

    total = len(subs)
    max_cycle = min(args.max_cycle, max(s["cycles"] for s in subs) + 1)

    table = []
    for c in range(1, max_cycle + 1):
        # Only subscribers who reached this cycle can be judged at it. A member
        # who is active on cycle 2 has not survived to cycle 5 and has not
        # churned before it either; they are simply not in this denominator.
        reached = [s for s in subs if s["cycles"] >= c]
        if not reached:
            continue
        churned_here = [s for s in subs if s["cycles"] == c and s["kind"] != "active"]
        row = {
            "cycle": c,
            "reached": len(reached),
            "share_of_all_pct": round(len(reached) / total * 100.0, 1),
            "left_at_this_cycle": len(churned_here),
            "voluntary": sum(1 for s in churned_here if s["kind"] == "voluntary"),
            "involuntary": sum(1 for s in churned_here if s["kind"] == "involuntary"),
            "paused": sum(1 for s in churned_here if s["kind"] == "paused"),
        }
        row["churn_at_cycle_pct"] = round(row["left_at_this_cycle"] / len(reached) * 100.0, 1)
        table.append(row)

    ended = [s for s in subs if s["kind"] != "active"]
    split = {
        "voluntary": sum(1 for s in ended if s["kind"] == "voluntary"),
        "involuntary": sum(1 for s in ended if s["kind"] == "involuntary"),
        "paused_not_resumed": sum(1 for s in ended if s["kind"] == "paused"),
    }

    reasons = {}
    for s in ended:
        if s["reason"]:
            reasons[s["reason"].lower()] = reasons.get(s["reason"].lower(), 0) + 1
    top_reasons = sorted(reasons.items(), key=lambda kv: -kv[1])[:10]

    result = {
        "subscribers": total, "rows_skipped": skipped,
        "churn_type_inferred_for": inferred,
        "rows_never_billed_excluded_from_churn": never_billed,
        "ended": len(ended), "split": split,
        "survival": table, "top_reasons": top_reasons,
    }

    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    print("subscribers: %d   ended: %d   skipped rows: %d" % (total, len(ended), skipped))
    if ended:
        inv_share = split["involuntary"] / len(ended) * 100.0
        print("voluntary %d   involuntary %d (%.1f%% of all endings)   paused-not-resumed %d"
              % (split["voluntary"], split["involuntary"], inv_share, split["paused_not_resumed"]))
    if never_billed:
        print("NOTE: %d subscribers had not completed a cycle and are not counted "
              "as churn. They have not survived anything yet either." % never_billed)
    if inferred:
        print("NOTE: churn type was INFERRED from status/reason text for %d rows. "
              "The involuntary share is the number this whole analysis turns on, "
              "so confirm it against the billing platform before acting." % inferred)
    print()
    print("%7s %10s %12s %12s %14s %9s %9s"
          % ("cycle", "reached", "%of all", "left here", "churn at %", "volunt.", "involunt."))
    for r in table:
        print("%7d %10d %11.1f%% %12d %13.1f%% %9d %9d"
              % (r["cycle"], r["reached"], r["share_of_all_pct"], r["left_at_this_cycle"],
                 r["churn_at_cycle_pct"], r["voluntary"], r["involuntary"]))
    print()
    print("'reached' is the denominator at each cycle: subscribers who got that far.")
    print("Someone still active on cycle 2 has not churned before cycle 5, they are")
    print("simply not counted there.")

    if top_reasons:
        print()
        print("stated reasons (self-reported, treat as signal not proof):")
        for reason, n in top_reasons:
            print("  %-44s %d" % (reason[:44], n))

    if ended and split["involuntary"] / len(ended) > 0.25:
        print()
        print("READ: more than a quarter of endings are payment failures. That is a "
              "dunning and card-updater problem, not an offer problem, and it is "
              "cheaper to fix than anything else in this analysis.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
