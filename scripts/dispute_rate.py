#!/usr/bin/env python3
"""Rate and cluster disputes against the period they belong to.

Used by: chargeback-fraud-pattern-review-ecommerce

Why this exists: the dispute rate is almost always computed against the wrong
denominator. A dispute filed in March belongs to the transaction that happened
in January, so dividing this month's disputes by this month's orders understates
a rising problem and overstates a falling one. Getting that right is arithmetic,
not judgement, and doing it by hand is how a store reassures itself into a
provider warning.

Input: one CSV with a row per DISPUTE.

  amount, reason                      required
  transaction_date                    strongly recommended, the ORIGINAL sale date
  filed_date                          optional, when the dispute was raised
  outcome                             optional, won / lost / pending
  product                             optional

Order volume for the same period is passed as a flag, because it lives in a
different export:
  --orders-per-month "2026-01=1200,2026-02=1310"

usage:
  python3 scripts/dispute_rate.py disputes.csv
  python3 scripts/dispute_rate.py disputes.csv --orders-per-month "2026-01=1200" --json

exit 0 = ran, 2 = could not run.
"""
import argparse
import csv
import json
import math
import re
import sys
from datetime import datetime

ALIASES = {
    "amount": ["amount", "disputed amount", "value", "total"],
    "reason": ["reason", "reason code", "dispute reason", "category"],
    "transaction_date": ["transaction date", "charge date", "order date", "created",
                         "transaction_date", "sale date"],
    "filed_date": ["filed date", "dispute date", "opened", "filed_date", "due by"],
    "outcome": ["outcome", "status", "result", "resolution"],
    "product": ["product", "sku", "item", "product title"],
}
DATE_FORMATS = ["%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y"]

# Reason codes vary by scheme and change; these families are what the analysis
# turns on, and anything unmatched stays visible rather than being forced.
FAMILIES = [
    ("not_received", re.compile(r"not received|non.?receipt|undelivered|never arrived|13\.1", re.I)),
    ("not_as_described", re.compile(r"not as described|defect|damaged|quality|misrepresent|13\.3|13\.5", re.I)),
    ("subscription", re.compile(r"recurring|subscription|cancel|13\.2", re.I)),
    ("duplicate_or_error", re.compile(r"duplicate|processing error|incorrect amount|12\.", re.I)),
    ("fraud", re.compile(r"fraud|unauthori[sz]ed|10\.", re.I)),
]


def norm(s):
    return " ".join(str(s or "").strip().lower().replace("_", " ").split())


def parse_date(raw):
    s = str(raw or "").strip().split("T")[0].split(" ")[0]
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def money(raw):
    s = str(raw or "").strip()
    for ch in "()$£€ ,":
        s = s.replace(ch, "")
    value = abs(float(s))
    if not math.isfinite(value):
        raise ValueError("amount must be finite")
    return value


def family_of(reason):
    for name, pattern in FAMILIES:
        if pattern.search(reason or ""):
            return name
    return "unclassified"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--orders-per-month", default="",
                    help='e.g. "2026-01=1200,2026-02=1310"')
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
    missing = [k for k in ("amount", "reason") if k not in cm]
    if missing:
        print("missing required columns: %s" % ", ".join(missing), file=sys.stderr)
        print("columns found: %s" % ", ".join(rows[0].keys()), file=sys.stderr)
        return 2

    volumes = {}
    for part in filter(None, args.orders_per_month.split(",")):
        try:
            month, count = part.split("=", 1)
            month = month.strip()
            if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
                raise ValueError("expected YYYY-MM")
            value = float(count)
            if not math.isfinite(value) or value <= 0 or not value.is_integer():
                raise ValueError("order volume must be a positive finite integer")
            if month in volumes:
                raise ValueError("duplicate month")
            volumes[month] = value
        except ValueError as exc:
            print("invalid order volume %r: %s" % (part, exc), file=sys.stderr)
            return 2

    disputes, undated = [], 0
    for row_number, row in enumerate(rows, start=2):
        try:
            amount = money(row.get(cm["amount"]))
        except (TypeError, ValueError):
            print("invalid amount at CSV row %d: expected a finite number" % row_number,
                  file=sys.stderr)
            return 2
        reason = str(row.get(cm["reason"], "")).strip()
        tdate = parse_date(row.get(cm["transaction_date"])) if cm.get("transaction_date") else None
        fdate = parse_date(row.get(cm["filed_date"])) if cm.get("filed_date") else None
        if tdate is None:
            undated += 1
        disputes.append({
            "amount": amount,
            "reason": reason,
            "family": family_of(reason),
            "month": (tdate or fdate).strftime("%Y-%m") if (tdate or fdate) else None,
            "dated_by": "transaction" if tdate else ("filed" if fdate else None),
            "outcome": str(row.get(cm.get("outcome", ""), "")).strip() if cm.get("outcome") else "",
            "product": str(row.get(cm.get("product", ""), "")).strip() if cm.get("product") else "",
        })

    fams = {}
    for d in disputes:
        f = fams.setdefault(d["family"], {"count": 0, "value": 0.0})
        f["count"] += 1
        f["value"] += d["amount"]

    by_month = {}
    for d in disputes:
        if not d["month"]:
            continue
        m = by_month.setdefault(d["month"], {"count": 0, "value": 0.0, "rate_pct": None})
        m["count"] += 1
        m["value"] += d["amount"]
    for month, m in by_month.items():
        if month in volumes and volumes[month]:
            m["rate_pct"] = round(m["count"] / volumes[month] * 100.0, 3)

    total_value = sum(d["amount"] for d in disputes)
    result = {
        "disputes": len(disputes),
        "total_value": round(total_value, 2),
        "dated_by_transaction_date": sum(1 for d in disputes if d["dated_by"] == "transaction"),
        "dated_by_filing_date_only": sum(1 for d in disputes if d["dated_by"] == "filed"),
        "undated": undated,
        "families": {k: {"count": v["count"], "value": round(v["value"], 2),
                         "share_pct": round(v["count"] / len(disputes) * 100.0, 1)}
                     for k, v in sorted(fams.items(), key=lambda kv: -kv[1]["count"])},
        "by_month": {k: {"count": v["count"], "value": round(v["value"], 2),
                         "rate_pct": v["rate_pct"]} for k, v in sorted(by_month.items())},
        "months_without_order_volume": sorted(m for m in by_month if m not in volumes),
    }

    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    print("disputes: %d   total value: %.2f" % (result["disputes"], result["total_value"]))
    if not cm.get("transaction_date"):
        print("WARNING: no transaction date column. Disputes are being dated by "
              "when they were FILED, which belongs to the wrong period and will "
              "understate a rising rate. This is the single most common way a "
              "dispute rate reads better than it is.")
    elif result["dated_by_filing_date_only"]:
        print("NOTE: %d disputes had no transaction date and fell back to the "
              "filing date." % result["dated_by_filing_date_only"])
    print()
    print("%-20s %8s %12s %9s" % ("reason family", "count", "value", "share"))
    for name, f in result["families"].items():
        print("%-20s %8d %12.2f %8.1f%%" % (name, f["count"], f["value"], f["share_pct"]))
    if "unclassified" in result["families"]:
        print("  unclassified reasons stay visible rather than being forced into a "
              "family. Read them before drawing conclusions.")
    print()
    print("%-10s %8s %12s %10s" % ("month", "count", "value", "rate"))
    for month, m in result["by_month"].items():
        print("%-10s %8d %12.2f %10s"
              % (month, m["count"], m["value"],
                 "-" if m["rate_pct"] is None else "%.3f%%" % m["rate_pct"]))
    if result["months_without_order_volume"]:
        print()
        print("No order volume supplied for: %s. A count without a denominator is "
              "not a rate, so those months show a dash."
              % ", ".join(result["months_without_order_volume"]))

    service = sum(result["families"].get(k, {}).get("count", 0)
                  for k in ("not_received", "not_as_described", "subscription"))
    if service and service / len(disputes) > 0.4:
        print()
        print("READ: %.0f%% of disputes are service failures rather than fraud "
              "claims. Tightening fraud rules would not have prevented them, and "
              "would reject good orders instead."
              % (service / len(disputes) * 100))
    return 0


if __name__ == "__main__":
    sys.exit(main())
