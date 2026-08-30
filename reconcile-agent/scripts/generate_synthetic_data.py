from __future__ import annotations

import csv
import json
import os
import random
from datetime import date, datetime, timedelta, timezone


def generate_dataset(seed: int = 42) -> None:
    random.seed(seed)

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(base_dir, "data")
    fixtures_dir = os.path.join(base_dir, "tests", "fixtures")
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(fixtures_dir, exist_ok=True)

    start_date = date(2026, 8, 1)

    # 8 deterministic test groups mapping to daily settlements:
    # Group 1 (Day 0): 20 payments -> UTR20260801001 (EXACT MATCH)
    # Group 2 (Day 1): 15 payments -> UTR20260802001 (EXACT MATCH)
    # Group 3 (Day 2): 5 payments  -> UTR20260803001 (ROUNDING MATCH, +/- ₹1)
    # Group 4 (Day 3): 3 payments  -> UTR20260804001 (PARTIAL SETTLEMENT, 80% received)
    # Group 5 (Day 4): 2 payments  -> UTR20260805001 (DUPLICATE UTR, 2 rows in bank)
    # Group 6 (Day 5): 2 payments  -> UTR20260806001 (MISSING BANK ENTRY, 0 rows in bank)
    # Group 7 (Day 6): 1 payment   -> UTR20260807001 (AMOUNT MISMATCH, +₹500 delta)
    # Group 8 (Day 7): 2 payments  -> UTR20260808001 (EXACT MATCH)
    # Total payments = 20 + 15 + 5 + 3 + 2 + 2 + 1 + 2 = 50 payments

    group_configs = [
        {"count": 20, "day": 0, "utr": "UTR20260801001", "type": "EXACT"},
        {"count": 15, "day": 1, "utr": "UTR20260802001", "type": "EXACT"},
        {"count": 5,  "day": 2, "utr": "UTR20260803001", "type": "ROUNDING"},
        {"count": 3,  "day": 3, "utr": "UTR20260804001", "type": "PARTIAL"},
        {"count": 2,  "day": 4, "utr": "UTR20260805001", "type": "DUPLICATE"},
        {"count": 2,  "day": 5, "utr": "UTR20260806001", "type": "MISSING_BANK"},
        {"count": 1,  "day": 6, "utr": "UTR20260807001", "type": "MISMATCH"},
        {"count": 2,  "day": 7, "utr": "UTR20260808001", "type": "EXACT"},
    ]

    payments = []
    payment_idx = 1
    groups = []

    for gc in group_configs:
        g_date = start_date + timedelta(days=gc["day"])
        g_payment_indices = []

        for _ in range(gc["count"]):
            pay_id = f"pay_test_{payment_idx:04d}"
            order_id = f"order_test_{payment_idx:04d}"
            amount_paise = random.randint(100, 5000) * 100
            fee_paise = int(amount_paise * 0.02)
            tax_paise = int(fee_paise * 0.18)

            hour = random.randint(9, 18)
            minute = random.randint(0, 59)
            second = random.randint(0, 59)
            captured_dt = datetime(
                g_date.year, g_date.month, g_date.day, hour, minute, second, tzinfo=timezone.utc
            )
            created_at_ts = int(captured_dt.timestamp())

            p_data = {
                "id": pay_id,
                "order_id": order_id,
                "amount_paise": amount_paise,
                "fee_paise": fee_paise,
                "tax_paise": tax_paise,
                "status": "captured",
                "captured_at": captured_dt.isoformat(),
                "created_at": created_at_ts,
                "settlement_date": g_date.isoformat(),
                "customer_ref": f"CUST_{payment_idx:04d}",
                "expected_utr": gc["utr"],
                "group_type": gc["type"],
            }
            payments.append(p_data)
            g_payment_indices.append(len(payments) - 1)
            payment_idx += 1

        groups.append({
            "day": gc["day"],
            "utr": gc["utr"],
            "type": gc["type"],
            "indices": g_payment_indices,
            "date": g_date,
        })

    # 1. Save Razorpay Payments Fixture JSON (GET /v1/payments format)
    razorpay_fixture = {
        "entity": "collection",
        "count": len(payments),
        "items": [
            {
                "id": p["id"],
                "entity": "payment",
                "amount": p["amount_paise"],
                "currency": "INR",
                "status": "captured",
                "order_id": p["order_id"],
                "invoice_id": None,
                "international": False,
                "method": "card",
                "amount_refunded": 0,
                "refund_status": None,
                "captured": True,
                "description": f"Test Payment {p['id']}",
                "card_id": f"card_{p['id']}",
                "bank": None,
                "wallet": None,
                "vpa": None,
                "email": f"customer_{p['id']}@example.com",
                "contact": "+919876543210",
                "fee": p["fee_paise"],
                "tax": p["tax_paise"],
                "error_code": None,
                "error_description": None,
                "error_source": None,
                "error_step": None,
                "error_reason": None,
                "acquirer_data": {"auth_code": f"AUTH{p['id'][-4:]}"},
                "created_at": p["created_at"],
            }
            for p in payments
        ],
    }

    fixture_file_path = os.path.join(fixtures_dir, "razorpay_payments_50_mixed.json")
    with open(fixture_file_path, "w", encoding="utf-8") as f:
        json.dump(razorpay_fixture, f, indent=2)

    # 2. Save Ledger CSV
    ledger_file_path = os.path.join(data_dir, "synthetic_ledger.csv")
    with open(ledger_file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["order_id", "expected_amount_paise", "customer_ref", "invoice_date"])
        for p in payments:
            writer.writerow([
                p["order_id"],
                p["amount_paise"],
                p["customer_ref"],
                p["settlement_date"],
            ])

    # 3. Save Bank Statement CSV
    bank_file_path = os.path.join(data_dir, "synthetic_bank_statement.csv")
    bank_rows = []

    for g in groups:
        g_payments = [payments[i] for i in g["indices"]]
        gross = sum(p["amount_paise"] for p in g_payments)
        fee = sum(p["fee_paise"] for p in g_payments)
        tax = sum(p["tax_paise"] for p in g_payments)
        net = gross - fee - tax
        g_date = g["date"]

        if g["type"] == "EXACT":
            bank_rows.append({
                "utr": g["utr"],
                "amount_paise": net,
                "value_date": g_date.isoformat(),
                "narration": f"Razorpay Settlement {g['utr']}",
            })
        elif g["type"] == "ROUNDING":
            # ₹1.00 variance (+100 paise)
            bank_rows.append({
                "utr": g["utr"],
                "amount_paise": net + 100,
                "value_date": g_date.isoformat(),
                "narration": f"Razorpay Settlement {g['utr']} Rounding Adj",
            })
        elif g["type"] == "PARTIAL":
            # Bank receives 80% of net
            partial_net = int(net * 0.80)
            bank_rows.append({
                "utr": g["utr"],
                "amount_paise": partial_net,
                "value_date": g_date.isoformat(),
                "narration": f"Razorpay Partial Settlement {g['utr']}",
            })
        elif g["type"] == "DUPLICATE":
            # 2 bank rows with the exact same UTR
            bank_rows.append({
                "utr": g["utr"],
                "amount_paise": net,
                "value_date": g_date.isoformat(),
                "narration": f"Razorpay Settlement {g['utr']} Credit 1",
            })
            bank_rows.append({
                "utr": g["utr"],
                "amount_paise": net,
                "value_date": g_date.isoformat(),
                "narration": f"Razorpay Settlement {g['utr']} Credit 2 (Duplicate)",
            })
        elif g["type"] == "MISSING_BANK":
            # No bank row generated for this settlement
            pass
        elif g["type"] == "MISMATCH":
            # Wild variance (+₹500 / 50000 paise)
            bank_rows.append({
                "utr": g["utr"],
                "amount_paise": net + 50000,
                "value_date": g_date.isoformat(),
                "narration": f"Razorpay Settlement {g['utr']} Unreconciled Delta",
            })

    # Add 2 ORPHAN Bank entries (money arrived with no Razorpay payment behind it)
    orphan_date = start_date + timedelta(days=10)
    bank_rows.append({
        "utr": "UTR_ORPHAN_99901",
        "amount_paise": 250000,
        "value_date": orphan_date.isoformat(),
        "narration": "Direct NEFT Credit Unknown Ref UTR_ORPHAN_99901",
    })
    bank_rows.append({
        "utr": "UTR_ORPHAN_99902",
        "amount_paise": 150000,
        "value_date": orphan_date.isoformat(),
        "narration": "Manual Bank Transfer UTR_ORPHAN_99902",
    })

    with open(bank_file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["utr", "amount_paise", "value_date", "narration"])
        for row in bank_rows:
            writer.writerow([row["utr"], row["amount_paise"], row["value_date"], row["narration"]])

    # 4. Save Ground Truth JSON Oracle
    ground_truth = {
        "metadata": {
            "total_payments": 50,
            "expected_matched_payments": 42,
            "expected_exception_payments": 8,
            "expected_orphan_bank_entries": 2,
            "total_records": 52,
            "target_record_match_rate": 42 / 52,
        },
        "payment_expectations": [],
        "orphan_expectations": [
            {
                "utr": "UTR_ORPHAN_99901",
                "result_scope": "ORPHAN_BANK_ENTRY",
                "expected_decision": "EXCEPTION",
                "expected_reason_code": "MISSING_SETTLEMENT",
            },
            {
                "utr": "UTR_ORPHAN_99902",
                "result_scope": "ORPHAN_BANK_ENTRY",
                "expected_decision": "EXCEPTION",
                "expected_reason_code": "MISSING_SETTLEMENT",
            },
        ],
    }

    for p in payments:
        gtype = p["group_type"]
        if gtype == "EXACT":
            decision = "MATCH"
            reason_code = None
            match_method = "EXACT_UTR"
        elif gtype == "ROUNDING":
            decision = "MATCH"
            reason_code = None
            match_method = "AMOUNT_WITH_FEE_EQUATION"
        elif gtype == "PARTIAL":
            decision = "EXCEPTION"
            reason_code = "PARTIAL_SETTLEMENT"
            match_method = None
        elif gtype == "DUPLICATE":
            decision = "EXCEPTION"
            reason_code = "DUPLICATE_UTR"
            match_method = None
        elif gtype == "MISSING_BANK":
            decision = "EXCEPTION"
            reason_code = "MISSING_BANK_ENTRY"
            match_method = None
        elif gtype == "MISMATCH":
            decision = "EXCEPTION"
            reason_code = "AMOUNT_MISMATCH"
            match_method = None
        else:
            decision = "EXCEPTION"
            reason_code = "UNRESOLVED_AMBIGUOUS"
            match_method = None

        ground_truth["payment_expectations"].append({
            "payment_id": p["id"],
            "order_id": p["order_id"],
            "amount_paise": p["amount_paise"],
            "expected_utr": p["expected_utr"],
            "result_scope": "PAYMENT",
            "expected_decision": decision,
            "expected_reason_code": reason_code,
            "expected_match_method": match_method,
        })

    gt_file_path = os.path.join(data_dir, "ground_truth.json")
    with open(gt_file_path, "w", encoding="utf-8") as f:
        json.dump(ground_truth, f, indent=2)

    # 5. LLM Extraction Fixture (Low-confidence unresolvable response to preserve ground truth integrity)
    llm_fixture_path = os.path.join(fixtures_dir, "llm_narration_extraction_response.json")
    llm_fixture = {
        "candidate_order_id": None,
        "candidate_utr": None,
        "confidence": "low",
        "reasoning": "Unsolicited transfer, no valid UTR or order reference found in narration.",
    }
    with open(llm_fixture_path, "w", encoding="utf-8") as f:
        json.dump(llm_fixture, f, indent=2)

    print("Synthetic dataset regenerated cleanly.")


if __name__ == "__main__":
    generate_dataset()
