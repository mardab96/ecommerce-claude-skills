#!/usr/bin/env python3
"""Build customer cohorts from a raw order export.

Used by: ltv-cohort-read-ecommerce

Why this exists: cohort maths is where confident nonsense comes from. Grouping
customers by first-order month, tracking cumulative value at day 30/90/180/365,
and refusing to report a horizon the data has not reached yet are all mechanical
steps, and all three are easy for a model to fudge. This does them exactly and
prints the cohort size next to every number so nothing gets compared without it.

Input: one CSV with a row per ORDER.

  customer, order_date, order_value   required
  source                              optional, acquisition source of the customer
  first_product                       optional
  discount                            optional, discount on the order

Column names are matched case-insensitively with common export spellings.
Dates are parsed as YYYY-MM-DD, DD/MM/YYYY or MM/DD/YYYY (say which with
--date-format if the file is ambiguous).

Each horizon is averaged over the customers old enough to have reached it,
measured against the newest order in the file, and the count of those customers
is printed next to the value. A horizon nobody has reached prints "-", never a
zero. Maturity is judged per customer rather than per group, because a segment
like a channel keeps acquiring and would otherwise be blanked out by its
youngest member.

The file's newest order is the reference date, not today. A stale export makes
every cohort look more mature than it is, so check the printed "as of" date
against the calendar before quoting anything.

usage:
  python3 scripts/cohort_read.py orders.csv
  python3 scripts/cohort_read.py orders.csv --by source --json

exit 0 = ran, 2 = could not run.
"""
import argparse
import csv
import json
import statistics
import sys
from datetime import datetime

COLUMNS = {
    "customer": ["customer", "customer id", "customer_id", "email", "customer email", "buyer"],
    "order_date": ["order date", "order_date", "date", "created at", "processed at", "day"],
    "order_value": ["order value", "order_value", "total", "net sales", "revenue", "amount", "total price"],
    "source": ["source", "acquisition source", "utm_source", "channel", "referring channel"],
    "first_product": ["first product", "product", "product title", "first_product"],
    "discount": ["discount", "discounts", "discount amount"],
}
HORIZONS = [30, 90, 180, 365]
DATE_FORMATS = ["%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S"]


def norm(s):
    return " ".join(str(s or "").strip().lower().replace("_", " ").split())


def build_map(header):
    seen = {norm(h): h for h in header}
    out = {}
    for key, aliases in COLUMNS.items():
        for alias in aliases:
            if alias in seen:
                out[key] = seen[alias]
                break
    return out


def parse_date(raw, explicit=None):
    s = str(raw or "").strip()
    if not s:
        return None
    s = s.replace("Z", "").split("+")[0].strip()
    if " " in s and "T" not in s:
        s = s.split(" ")[0]
    fmts = [explicit] if explicit else DATE_FORMATS
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt).date()
        except (ValueError, TypeError):
            continue
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def money(raw):
    s = str(raw or "").strip()
    if not s:
        return 0.0
    neg = s.startswith("(") and s.endswith(")")
    for ch in "()$£€ ,":
        s = s.replace(ch, "")
    try:
        v = float(s)
    except ValueError:
        return 0.0
    return -v if neg else v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--by", choices=["cohort", "source", "first_product"], default="cohort")
    ap.add_argument("--date-format", default=None)
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

    cm = build_map(rows[0].keys())
    missing = [k for k in ("customer", "order_date", "order_value") if k not in cm]
    if missing:
        print("missing required columns: %s" % ", ".join(missing), file=sys.stderr)
        print("columns found: %s" % ", ".join(rows[0].keys()), file=sys.stderr)
        return 2
    if args.by != "cohort" and args.by not in cm:
        print("cannot segment by %s: column not in the export" % args.by, file=sys.stderr)
        return 2

    orders = []
    unparsed = 0
    for row in rows:
        cust = str(row.get(cm["customer"], "")).strip().lower()
        date = parse_date(row.get(cm["order_date"]), args.date_format)
        if not cust or date is None:
            unparsed += 1
            continue
        orders.append({
            "customer": cust,
            "date": date,
            "value": money(row.get(cm["order_value"])),
            "source": str(row.get(cm.get("source", ""), "")).strip() if cm.get("source") else "",
            "first_product": str(row.get(cm.get("first_product", ""), "")).strip() if cm.get("first_product") else "",
        })
    if not orders:
        print("no parseable orders", file=sys.stderr)
        return 2

    orders.sort(key=lambda o: o["date"])
    as_of = orders[-1]["date"]

    customers = {}
    for o in orders:
        c = customers.setdefault(o["customer"], {"first": o["date"], "orders": []})
        c["orders"].append(o)
    for c in customers.values():
        c["orders"].sort(key=lambda o: o["date"])
        c["first"] = c["orders"][0]["date"]
        c["source"] = c["orders"][0]["source"]
        c["first_product"] = c["orders"][0]["first_product"]

    def key_for(c):
        if args.by == "cohort":
            return c["first"].strftime("%Y-%m")
        return c[args.by] or "(unknown)"

    groups = {}
    for c in customers.values():
        groups.setdefault(key_for(c), []).append(c)

    second_gaps = []
    for c in customers.values():
        if len(c["orders"]) > 1:
            second_gaps.append((c["orders"][1]["date"] - c["first"]).days)
    second_gaps.sort()
    median_gap = statistics.median(second_gaps) if second_gaps else None

    report = []
    for name in sorted(groups):
        members = groups[name]
        n = len(members)
        row = {"group": name, "customers": n}
        repeat = sum(1 for c in members if len(c["orders"]) > 1)
        row["repeat_rate_pct"] = round(repeat / n * 100.0, 1)
        for hz in HORIZONS:
            # Maturity is a property of the CUSTOMER, not of the group. A monthly
            # cohort is uniform, but a segment like "meta" or "the blue hoodie"
            # keeps acquiring, so it always contains someone who signed up
            # yesterday. Gating the whole group on its youngest member would
            # blank out a channel with thousands of mature customers because one
            # arrived this morning, which is exactly what makes the payback
            # comparison this script exists for impossible.
            mature = [c for c in members if (as_of - c["first"]).days >= hz]
            row["d%d_mature" % hz] = len(mature)
            if not mature:
                row["d%d" % hz] = None
                continue
            total = 0.0
            for c in mature:
                total += sum(o["value"] for o in c["orders"] if (o["date"] - c["first"]).days <= hz)
            row["d%d" % hz] = round(total / len(mature), 2)
        report.append(row)

    summary = {
        "orders_parsed": len(orders),
        "rows_skipped": unparsed,
        "customers": len(customers),
        "as_of": as_of.isoformat(),
        "median_days_to_second_order": median_gap,
        "repeat_customers": sum(1 for c in customers.values() if len(c["orders"]) > 1),
        "segmented_by": args.by,
    }

    if args.json:
        print(json.dumps({"summary": summary, "groups": report}, indent=2))
        return 0

    print("orders parsed: %d   customers: %d   skipped rows: %d   as of: %s"
          % (summary["orders_parsed"], summary["customers"], unparsed, as_of))
    print("median days to second order: %s   repeat customers: %d"
          % (median_gap if median_gap is not None else "no repeat orders in file",
             summary["repeat_customers"]))
    print()
    print("%-14s %10s %9s %14s %14s %14s %14s"
          % (args.by, "customers", "repeat_%", "d30 (n)", "d90 (n)", "d180 (n)", "d365 (n)"))
    for r in report:
        cells = []
        for hz in HORIZONS:
            v = r["d%d" % hz]
            m = r["d%d_mature" % hz]
            cells.append("-" if v is None else "%.2f (%d)" % (v, m))
        print("%-14s %10d %9.1f %14s %14s %14s %14s"
              % (r["group"], r["customers"], r["repeat_rate_pct"], *cells))
    print()
    print("Each horizon is averaged over the customers OLD ENOUGH to have reached it,")
    print("and (n) is how many that was, measured against %s. A dash means nobody in" % as_of)
    print("that group has reached the horizon yet. It is not a zero, and a small (n)")
    print("is not a comparable number: say the n whenever you quote the value.")
    if (as_of - orders[0]["date"]).days < 365:
        print()
        print("NOTE: this export spans %d days, so no 365-day horizon can exist in it."
              % (as_of - orders[0]["date"]).days)
    return 0


if __name__ == "__main__":
    sys.exit(main())
