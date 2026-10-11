#!/usr/bin/env python3
"""Regression tests for the seven analysis scripts.

    python3 scripts/selftest.py

Every case below is a bug that actually shipped and was caught by someone
running the scripts against a fixture rather than reading them. They are here so
the same bug cannot come back quietly. If you change a script, run this first.

The pack's whole claim is that these scripts do not produce confidently wrong
numbers. That claim is only worth what this file checks.

exit 0 = all guarantees hold, 1 = a guarantee broke.
"""
import csv
import json
import os
import subprocess
import sys
import tempfile
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
FAILURES = []


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)


def run(script, *args):
    proc = subprocess.run([sys.executable, os.path.join(HERE, script)] + list(args),
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def run_json(script, *args):
    rc, out, err = run(script, *(args + ("--json",)))
    if rc != 0:
        return rc, None, err
    return rc, json.loads(out), err


def check(name, condition, detail=""):
    if condition:
        print("  pass  %s" % name)
    else:
        print("  FAIL  %s %s" % (name, detail))
        FAILURES.append(name)


def test_margin(tmp):
    print("margin_stack.py")
    # A discount written as -100 must subtract exactly like one written as 100.
    path = os.path.join(tmp, "sign.csv")
    write_csv(path, [
        ["SKU", "Units", "Net sales", "Discounts", "Cost per item", "Shipping cost"],
        ["POS", 100, 1000, 100, 3, 50],
        ["NEG", 100, 1000, -100, 3, 50],
    ])
    rc, data, err = run_json("margin_stack.py", path)
    if rc != 0:
        return check("negative discounts subtract", False, err)
    by = {r["sku"]: r for r in data["skus"]}
    check("negative discounts subtract, they do not add back",
          by["POS"]["cm2"] == by["NEG"]["cm2"],
          "POS=%s NEG=%s" % (by["POS"]["cm2"], by["NEG"]["cm2"]))

    # A stack with no COGS column must not print a margin percentage.
    path = os.path.join(tmp, "nocogs.csv")
    write_csv(path, [["SKU", "Units", "Net sales"], ["A", 10, 500]])
    rc, data, err = run_json("margin_stack.py", path)
    row = data["skus"][0]
    check("no margin percentage is derived when COGS is absent",
          row["cm2_pct"] is None and row["breakeven_roas"] is None,
          "cm2_pct=%s breakeven=%s" % (row["cm2_pct"], row["breakeven_roas"]))

    # A fixed per-order fee must not be charged once per unit.
    path = os.path.join(tmp, "fee.csv")
    write_csv(path, [
        ["SKU", "Units", "Orders", "Net sales", "Cost per item"],
        ["A", 300, 100, 3000, 5],
    ])
    rc, with_orders, _ = run_json("margin_stack.py", path, "--payment-fee-fixed", "0.30")
    path2 = os.path.join(tmp, "fee_nounits.csv")
    write_csv(path2, [["SKU", "Units", "Net sales", "Cost per item"], ["A", 300, 3000, 5]])
    rc, without, _ = run_json("margin_stack.py", path2, "--payment-fee-fixed", "0.30")
    check("a fixed fee uses the orders column when it exists",
          with_orders["skus"][0]["cm2"] > without["skus"][0]["cm2"],
          "with_orders=%s per_unit=%s" % (with_orders["skus"][0]["cm2"], without["skus"][0]["cm2"]))

    rc, _, err = run("margin_stack.py", os.path.join(tmp, "does-not-exist.csv"))
    check("a missing file exits 2", rc == 2, "rc=%d" % rc)


def test_cohort(tmp):
    print("cohort_read.py")
    # One brand-new customer must not blank out a segment full of mature ones.
    path = os.path.join(tmp, "orders.csv")
    today = date(2026, 7, 27)
    rows = [["Customer", "Order date", "Total", "Source"]]
    for i in range(200):
        first = today - timedelta(days=400)
        rows.append(["m%03d" % i, first.isoformat(), 100, "meta"])
        rows.append(["m%03d" % i, (first + timedelta(days=60)).isoformat(), 80, "meta"])
    rows.append(["newbie", (today - timedelta(days=1)).isoformat(), 50, "meta"])
    write_csv(path, rows)
    rc, data, err = run_json("cohort_read.py", path, "--by", "source")
    if rc != 0:
        return check("segment maturity is per customer", False, err)
    meta = [g for g in data["groups"] if g["group"] == "meta"][0]
    check("one new customer does not blank a mature segment",
          meta["d365"] is not None, "d365=%s" % meta["d365"])
    check("the mature count is reported next to the horizon",
          meta["d365_mature"] == 200, "mature=%s" % meta["d365_mature"])

    # A horizon nobody has reached must be absent, not zero.
    path = os.path.join(tmp, "young.csv")
    write_csv(path, [["Customer", "Order date", "Total"],
                     ["a", (today - timedelta(days=10)).isoformat(), 50]])
    rc, data, _ = run_json("cohort_read.py", path)
    check("an unreached horizon is null, never zero",
          data["groups"][0]["d365"] is None, data["groups"][0]["d365"])


def test_catalog(tmp):
    print("catalog_scan.py")
    # Shopify writes one row per variant. Products must not be counted per row,
    # and the image count must be the product's, not the first row's.
    path = os.path.join(tmp, "catalog.csv")
    rows = [["Handle", "Title", "Body (HTML)", "Product type", "Image count", "Revenue"]]
    for i in range(30):
        rows.append(["p%02d" % i, "Product %d" % i,
                     "<p>" + ("Real sentence. " * 20) + "</p>", "Tees", 1, 500])
        rows.append(["p%02d" % i, "", "", "", 8, ""])
        rows.append(["p%02d" % i, "", "", "", 4, ""])
    write_csv(path, rows)
    rc, data, err = run_json("catalog_scan.py", path)
    if rc != 0:
        return check("variant rows collapse", False, err)
    s = data["summary"]
    check("variant rows collapse into one product each",
          s["products"] == 30, "products=%d" % s["products"])
    check("continuation rows are not counted as empty descriptions",
          s["empty_descriptions"] == 0, "empty=%d" % s["empty_descriptions"])
    check("the highest image count across variants wins",
          s.get("variant_rows_collapsed") == 60
          and not any(p["image_gap"] for p in data["work_queue_top50"]),
          "collapsed=%s" % s.get("variant_rows_collapsed"))


def test_promo(tmp):
    print("promo_impact.py")
    # Two gappy windows must both be reported, not just the last one.
    path = os.path.join(tmp, "daily.csv")
    rows = [["Date", "Revenue"]]
    for d in (date(2026, 11, 28), date(2026, 11, 29)):
        rows.append([d.isoformat(), 4000])
    write_csv(path, rows)
    rc, data, err = run_json("promo_impact.py", path,
                             "--promo-start", "2026-11-27", "--promo-end", "2026-11-30")
    if rc != 0:
        return check("coverage warnings accumulate", False, err)
    check("every gappy window is reported, not only the last",
          len(data["coverage_warnings"]) >= 2,
          "warnings=%s" % data["coverage_warnings"])

    # A promo whose trough cancels the peak must not read as growth.
    path = os.path.join(tmp, "pullforward.csv")
    rows = [["Date", "Revenue"]]
    start = date(2026, 10, 1)
    for i in range(90):
        d = start + timedelta(days=i)
        if date(2026, 11, 1) <= d <= date(2026, 11, 5):
            rev = 5000
        elif date(2026, 11, 6) <= d <= date(2026, 11, 10):
            rev = 100
        else:
            rev = 1000
        rows.append([d.isoformat(), rev])
    write_csv(path, rows)
    rc, data, _ = run_json("promo_impact.py", path,
                           "--promo-start", "2026-11-01", "--promo-end", "2026-11-05")
    check("the trough after a promo is measured and negative",
          data["trough_per_day_vs_baseline"] < 0,
          "trough=%s" % data["trough_per_day_vs_baseline"])


def test_shipping(tmp):
    print("shipping_recovery.py")
    for label, values, expected in (
        ("even", [10, 50], 30),
        ("odd", [10, 30, 50], 30),
        ("single", [20], 20),
        ("decimal", [10.5, 20.5], 15.5),
        ("repeated", [20, 20, 20, 20], 20),
    ):
        path = os.path.join(tmp, "shipping_median_%s.csv" % label)
        write_csv(path, [["Order value", "Shipping charged", "Shipping cost"]]
                  + [[value, 0, 5] for value in values])
        rc, data, err = run_json("shipping_recovery.py", path, "--threshold", "40")
        check("%s shipping median is correct" % label,
              rc == 0 and data["threshold"]["median_order_value"] == expected,
              str(data) if rc == 0 else err)
    # Refund rows carry a negative order value and belong to no band. The
    # overall total and the band table must not disagree about them.
    path = os.path.join(tmp, "ship.csv")
    write_csv(path, [
        ["Order value", "Shipping charged", "Shipping cost"],
        [30, 4.95, 6.0],
        [80, 0, 7.0],
        [-30, 0, 0],
    ])
    rc, data, err = run_json("shipping_recovery.py", path)
    if rc != 0:
        return check("negative order values", False, err)
    banded = sum(b["orders"] for b in data["by_band"])
    check("refund rows are excluded from the total, not just from the bands",
          banded == data["overall"]["orders"],
          "banded=%d overall=%d" % (banded, data["overall"]["orders"]))
    check("excluded refund rows are reported",
          data["negative_value_rows_excluded"] == 1,
          data["negative_value_rows_excluded"])


def test_subscription(tmp):
    print("subscription_survival.py")
    # A trialing subscriber who never billed is not a cancellation.
    path = os.path.join(tmp, "subs.csv")
    write_csv(path, [
        ["Subscriber", "Status", "Cycles", "Reason"],
        ["a", "trialing", 0, ""],
        ["b", "cancelled", 3, "too expensive"],
        ["c", "cancelled", 2, "payment failed - card declined"],
    ])
    rc, data, err = run_json("subscription_survival.py", path)
    if rc != 0:
        return check("trialing is not churn", False, err)
    check("a trialing subscriber is not counted as a cancellation",
          data["ended"] == 2, "ended=%d" % data["ended"])
    check("voluntary and involuntary are split, not blended",
          data["split"]["voluntary"] == 1 and data["split"]["involuntary"] == 1,
          data["split"])

    # Someone who never completed a cycle cannot have churned out of one.
    path = os.path.join(tmp, "neverbilled.csv")
    write_csv(path, [["Subscriber", "Status", "Cycles"], ["a", "cancelled", 0]])
    rc, data, _ = run_json("subscription_survival.py", path)
    check("a subscriber who never billed is not churn",
          data["ended"] == 0 and data["rows_never_billed_excluded_from_churn"] == 1,
          "ended=%d" % data["ended"])


def test_disputes(tmp):
    print("dispute_rate.py")
    # A dispute belongs to the month of the SALE, not the month it was filed.
    path = os.path.join(tmp, "disputes.csv")
    write_csv(path, [
        ["Amount", "Reason", "Transaction date", "Filed date"],
        [100, "Fraud - unauthorized", "2026-01-15", "2026-03-02"],
        [100, "Product not received", "2026-01-20", "2026-03-04"],
    ])
    rc, data, err = run_json("dispute_rate.py", path, "--orders-per-month", "2026-01=1000")
    if rc != 0:
        return check("disputes date to the transaction", False, err)
    check("disputes are dated to the sale, not to the filing",
          "2026-01" in data["by_month"] and "2026-03" not in data["by_month"],
          list(data["by_month"]))
    check("a month with order volume gets a rate",
          data["by_month"]["2026-01"]["rate_pct"] == 0.2,
          data["by_month"]["2026-01"]["rate_pct"])

    # A month with no order volume must show no rate rather than a fake one.
    rc, data, _ = run_json("dispute_rate.py", path)
    check("a count without a denominator is not reported as a rate",
          data["by_month"]["2026-01"]["rate_pct"] is None,
          data["by_month"]["2026-01"]["rate_pct"])


def main():
    with tempfile.TemporaryDirectory() as tmp:
        for fn in (test_margin, test_cohort, test_catalog,
                   test_promo, test_shipping, test_subscription, test_disputes):
            fn(tmp)
            print()
    if FAILURES:
        print("FAIL: %d guarantee(s) broken: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("OK: every documented guarantee holds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
