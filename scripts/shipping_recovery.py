#!/usr/bin/env python3
"""Compare shipping charged against shipping paid, by zone and order value.

Used by: shipping-economics-review-ecommerce

Why this exists: the shipping gap is invisible in aggregate and obvious once you
band it. A store recovering 92% overall can still lose money on every order under
a threshold, and that is the finding. Banding, per-zone recovery and the
threshold test against the real order distribution are all counting problems, so
they belong here rather than in an estimate.

Input: one CSV with a row per ORDER.

  order_value, shipping_charged, shipping_cost   required
  zone or country                                optional, gives per-zone recovery

usage:
  python3 scripts/shipping_recovery.py orders.csv
  python3 scripts/shipping_recovery.py orders.csv --threshold 50 --json

exit 0 = ran, 2 = could not run.
"""
import argparse
import csv
import json
import statistics
import sys

ALIASES = {
    "order_value": ["order value", "order_value", "subtotal", "total", "net sales", "revenue"],
    "shipping_charged": ["shipping charged", "shipping_charged", "shipping", "shipping revenue",
                         "shipping collected", "shipping price"],
    "shipping_cost": ["shipping cost", "shipping_cost", "carrier cost", "fulfilment cost",
                      "fulfillment cost", "postage"],
    "zone": ["zone", "country", "shipping country", "region", "destination"],
}
BANDS = [(0, 25), (25, 50), (50, 75), (75, 100), (100, 150), (150, 250), (250, None)]


def norm(s):
    return " ".join(str(s or "").strip().lower().replace("_", " ").split())


def money(raw):
    s = str(raw or "").strip()
    if not s:
        return None
    neg = s.startswith("(") and s.endswith(")")
    for ch in "()$£€ ,":
        s = s.replace(ch, "")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def band_label(lo, hi):
    return "%d-%d" % (lo, hi) if hi is not None else "%d+" % lo


def summarise(rows):
    charged = sum(r["charged"] for r in rows)
    cost = sum(r["cost"] for r in rows)
    return {
        "orders": len(rows),
        "charged": round(charged, 2),
        "cost": round(cost, 2),
        "gap": round(charged - cost, 2),
        "recovery_pct": round(charged / cost * 100.0, 1) if cost else None,
        "gap_per_order": round((charged - cost) / len(rows), 2) if rows else 0.0,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--threshold", type=float, default=None,
                    help="current free shipping threshold, tested against the real distribution")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        with open(args.csv_path, newline="", encoding="utf-8-sig") as fh:
            raw_rows = list(csv.DictReader(fh))
    except OSError as exc:
        print("could not read %s: %s" % (args.csv_path, exc), file=sys.stderr)
        return 2
    if not raw_rows:
        print("no rows", file=sys.stderr)
        return 2

    header = {norm(h): h for h in raw_rows[0].keys()}
    cm = {}
    for key, aliases in ALIASES.items():
        for alias in aliases:
            if alias in header:
                cm[key] = header[alias]
                break
    missing = [k for k in ("order_value", "shipping_charged", "shipping_cost") if k not in cm]
    if missing:
        print("missing required columns: %s" % ", ".join(missing), file=sys.stderr)
        print("columns found: %s" % ", ".join(raw_rows[0].keys()), file=sys.stderr)
        return 2

    orders, skipped, negative_rows = [], 0, 0
    for row in raw_rows:
        value = money(row.get(cm["order_value"]))
        cost = money(row.get(cm["shipping_cost"]))
        charged = money(row.get(cm["shipping_charged"]))
        if value is None or cost is None:
            skipped += 1
            continue
        if value < 0:
            # refund and adjustment rows carry a negative order value. They
            # belong to no value band, so counting them in the total while
            # dropping them from every band makes the two disagree silently.
            negative_rows += 1
            continue
        orders.append({
            "value": value,
            "cost": abs(cost),
            "charged": abs(charged) if charged is not None else 0.0,
            "zone": str(row.get(cm.get("zone", ""), "")).strip() or "(unknown)" if cm.get("zone") else "(all)",
        })
    if not orders:
        print("no usable orders", file=sys.stderr)
        return 2

    overall = summarise(orders)

    by_band = []
    for lo, hi in BANDS:
        sel = [o for o in orders if o["value"] >= lo and (hi is None or o["value"] < hi)]
        if not sel:
            continue
        s = summarise(sel)
        s["band"] = band_label(lo, hi)
        by_band.append(s)

    by_zone = []
    if cm.get("zone"):
        zones = {}
        for o in orders:
            zones.setdefault(o["zone"], []).append(o)
        for z, sel in sorted(zones.items(), key=lambda kv: -len(kv[1])):
            s = summarise(sel)
            s["zone"] = z
            by_zone.append(s)

    values = sorted(o["value"] for o in orders)
    median_value = statistics.median(values)
    threshold_read = None
    if args.threshold is not None:
        below = [o for o in orders if o["value"] < args.threshold]
        above = [o for o in orders if o["value"] >= args.threshold]
        just_above = [o for o in above if o["value"] < args.threshold * 1.15]
        threshold_read = {
            "threshold": args.threshold,
            "orders_below": len(below),
            "orders_above": len(above),
            "share_above_pct": round(len(above) / len(orders) * 100.0, 1),
            "orders_just_above_pct": round(len(just_above) / len(orders) * 100.0, 1),
            "gap_on_orders_above": summarise(above)["gap"] if above else 0.0,
            "median_order_value": median_value,
        }

    result = {"overall": overall, "by_band": by_band, "by_zone": by_zone,
              "threshold": threshold_read, "rows_skipped": skipped,
              "negative_value_rows_excluded": negative_rows}

    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    print("orders: %d   charged: %.2f   carrier cost: %.2f   gap: %+.2f   recovery: %s"
          % (overall["orders"], overall["charged"], overall["cost"], overall["gap"],
             "-" if overall["recovery_pct"] is None else "%.1f%%" % overall["recovery_pct"]))
    if skipped:
        print("rows skipped for unreadable values: %d" % skipped)
    if negative_rows:
        print("rows excluded as refunds or adjustments (negative order value): %d" % negative_rows)
    print()
    print("%-10s %8s %12s %12s %12s %10s" % ("band", "orders", "charged", "cost", "gap", "gap/order"))
    for b in by_band:
        print("%-10s %8d %12.2f %12.2f %12.2f %10.2f"
              % (b["band"], b["orders"], b["charged"], b["cost"], b["gap"], b["gap_per_order"]))
    if by_zone:
        print()
        print("%-18s %8s %12s %10s" % ("zone", "orders", "gap", "recovery"))
        for z in by_zone[:12]:
            print("%-18s %8d %12.2f %10s"
                  % (z["zone"][:18], z["orders"], z["gap"],
                     "-" if z["recovery_pct"] is None else "%.1f%%" % z["recovery_pct"]))

    losing = [b for b in by_band if b["gap"] < 0]
    if losing:
        print()
        print("Bands losing money on delivery: %s"
              % ", ".join("%s (%d orders, %+.2f)" % (b["band"], b["orders"], b["gap"]) for b in losing))

    if threshold_read:
        t = threshold_read
        print()
        print("Threshold %.2f: %d orders below, %d above (%.1f%% of orders)."
              % (t["threshold"], t["orders_below"], t["orders_above"], t["share_above_pct"]))
        print("Median order value is %.2f." % t["median_order_value"])
        if t["median_order_value"] > t["threshold"]:
            print("READ: the median order already clears the threshold, so most free "
                  "delivery is going to orders that would have qualified anyway. "
                  "That is subsidy, not basket building.")
        if t["orders_just_above_pct"] < 5:
            print("READ: only %.1f%% of orders land just above the threshold, which is "
                  "weak evidence that it changes behaviour at all."
                  % t["orders_just_above_pct"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
