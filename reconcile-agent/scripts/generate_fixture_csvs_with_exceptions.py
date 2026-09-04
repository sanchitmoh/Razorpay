#!/usr/bin/env python3
"""
Generate matching CSV fixtures with intentional exceptions based on ground_truth.json

This script creates REALISTIC exceptions that mirror real-world financial reconciliation challenges:

1. MISSING_BANK_ENTRY: Payments captured but never settled (settlement failed/pending)
2. PARTIAL_SETTLEMENT: Payments settled in parts (45%, 68%, 33%) with date delays
3. DUPLICATE_UTR: Multiple payments incorrectly grouped under same bank UTR
4. AMOUNT_MISMATCH: Off by ~50 INR due to bank charges, rounding, or fee calculation errors
5. MISSING_SETTLEMENT (orphans): Bank entries with no matching payment (refunds? manual transfers?)

These edge cases force the RAG system to:
- Explain complex multi-payment settlements
- Identify subtle amount discrepancies
- Trace missing entries across 3 data sources
- Handle temporal mismatches (T+1 settlements)
- Distinguish between similar exception types
"""

import json
import csv
from datetime import date, datetime, timezone
from collections import defaultdict
import os

# Paths
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fixtures_dir = os.path.join(base_dir, "tests", "fixtures")
data_dir = os.path.join(base_dir, "data")

fixture_json = os.path.join(fixtures_dir, "razorpay_payments_50_mixed.json")
ground_truth_json = os.path.join(data_dir, "ground_truth.json")

# Load fixture payments
with open(fixture_json, 'r', encoding='utf-8') as f:
    data = json.load(f)
    payments = data.get('items', [])

# Load ground truth expectations
with open(ground_truth_json, 'r', encoding='utf-8') as f:
    ground_truth = json.load(f)
    payment_expectations = {p['payment_id']: p for p in ground_truth['payment_expectations']}

print(f"Loaded {len(payments)} payments from fixture")
print(f"Loaded {len(payment_expectations)} payment expectations from ground truth")

# Find which payments should be exceptions
exception_payments = {
    pid: exp for pid, exp in payment_expectations.items() 
    if exp.get('expected_decision') == 'EXCEPTION'
}
print(f"Found {len(exception_payments)} expected exceptions:")
for pid, exp in exception_payments.items():
    print(f"  - {pid}: {exp.get('expected_reason_code')}")

# Generate ledger CSV (all payments in ledger)
ledger_path = os.path.join(fixtures_dir, "fixture_ledger_50.csv")
with open(ledger_path, 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow(['order_id', 'expected_amount_paise', 'customer_ref', 'invoice_date'])
    for p in payments:
        writer.writerow([
            p.get('order_id', 'order_unknown'),
            p['amount'],
            p.get('email', 'customer@example.com'),
            date.today().isoformat()
        ])

print(f"✅ Created {ledger_path}")

# Generate bank statement CSV with intentional exceptions
# Group payments by expected UTR from ground truth
utr_groups = defaultdict(list)
payments_by_id = {p['id']: p for p in payments}

for pid, exp in payment_expectations.items():
    if pid not in payments_by_id:
        continue
    
    p = payments_by_id[pid]
    expected_utr = exp.get('expected_utr')
    reason = exp.get('expected_reason_code')
    
    # Skip payments that should have MISSING_BANK_ENTRY exception
    if reason == 'MISSING_BANK_ENTRY':
        print(f"  Skipping {pid} from bank statement (MISSING_BANK_ENTRY)")
        continue
    
    # For PARTIAL_SETTLEMENT: these payments will be added separately (not in main settlement)
    if reason == 'PARTIAL_SETTLEMENT':
        print(f"  Will create partial settlement for {pid} (PARTIAL_SETTLEMENT)")
        continue
    
    # For AMOUNT_MISMATCH: will be added to group but amount will be modified
    # For DUPLICATE_UTR: multiple payments will share same UTR
    # For normal MATCH: group by UTR
    utr_groups[expected_utr].append((pid, p, reason))

bank_path = os.path.join(fixtures_dir, "fixture_bank_statement_50.csv")
with open(bank_path, 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow(['utr', 'amount_paise', 'value_date', 'narration'])
    
    # Process each UTR group
    for utr, pay_list in sorted(utr_groups.items()):
        # Calculate settlement amounts
        gross = 0
        fee_total = 0
        tax_total = 0
        
        has_amount_mismatch = False
        for pid, p, reason in pay_list:
            gross += p['amount']
            fee = p.get('fee', int(p['amount'] * 0.02))
            tax = p.get('tax', int(fee * 0.18))
            fee_total += fee
            tax_total += tax
            
            if reason == 'AMOUNT_MISMATCH':
                has_amount_mismatch = True
                print(f"  Modifying amount for {pid} (AMOUNT_MISMATCH)")
        
        net = gross - fee_total - tax_total
        
        # If AMOUNT_MISMATCH, alter the net amount in realistic ways
        if has_amount_mismatch:
            # Simulate common real-world mismatches:
            # - Bank charges not accounted for (subtract 50 paise)
            # - Rounding differences
            # - Wrong fee calculation
            net = int(net - 5000 + (net % 100))  # Off by 50 rupees + rounding error
            print(f"  Creating amount mismatch: expected vs actual differs by ~50 INR")
        
        # Extract date from UTR (format: UTR20260801001)
        try:
            date_str = utr[3:11]  # Extract YYYYMMDD
            p_date = datetime.strptime(date_str, '%Y%m%d').date()
        except:
            p_date = date.today()
        
        writer.writerow([utr, net, p_date.isoformat(), f'RZP-{utr[-6:]}-SETTLEMENT'])  # Abbreviated format
    
    # Add PARTIAL_SETTLEMENT entries (separate bank entries for partial amounts)
    # Make these realistic: different partial percentages, split across dates
    partial_percentages = [0.45, 0.68, 0.33]  # Irregular partial amounts
    for idx, (pid, exp) in enumerate([item for item in exception_payments.items() if item[1].get('expected_reason_code') == 'PARTIAL_SETTLEMENT']):
        if pid in payments_by_id:
            p = payments_by_id[pid]
            utr = exp.get('expected_utr')
            # Create partial settlement with varying percentages
            gross = p['amount']
            fee = p.get('fee', int(gross * 0.02))
            tax = p.get('tax', int(fee * 0.18))
            net = gross - fee - tax
            
            partial_pct = partial_percentages[idx % len(partial_percentages)]
            partial_net = int(net * partial_pct)
            
            try:
                date_str = utr[3:11]
                p_date = datetime.strptime(date_str, '%Y%m%d').date()
            except:
                p_date = date.today()
            
            # For the first partial, add it on a different date (T+1) to simulate delayed settlement
            if idx == 0:
                from datetime import timedelta
                p_date = p_date + timedelta(days=1)
            
            writer.writerow([utr, partial_net, p_date.isoformat(), f'Partial Sett. {utr[-8:]}'])  # Different narration format
            print(f"  Added partial settlement for {pid} ({int(partial_pct*100)}% settled, delayed: {idx==0})")
    
    # Add orphan bank entries (MISSING_SETTLEMENT exceptions)
    # Make these realistic: plausible amounts, dates that don't match any settlement
    orphan_expectations = ground_truth.get('orphan_expectations', [])
    print(f"Adding {len(orphan_expectations)} orphan bank entries (realistic edge cases)")
    orphan_amounts = [273845, 156320]  # Realistic orphan amounts (not round numbers)
    orphan_dates = ['2026-08-09', '2026-08-12']  # Dates with no matching payments
    for idx, orphan in enumerate(orphan_expectations):
        utr = orphan.get('utr', f'UTR_ORPHAN_UNKNOWN')
        amount = orphan_amounts[idx % len(orphan_amounts)]
        orphan_date = orphan_dates[idx % len(orphan_dates)]
        writer.writerow([utr, amount, orphan_date, f'INB-NEFT-{utr[-5:]}-RZP'])  # Different bank narration pattern
        print(f"  Added orphan: {utr} for {amount/100:.2f} INR on {orphan_date}")

print(f"✅ Created {bank_path}")
print(f"\n📋 Summary:")
print(f"   - {len(payments)} payments in ledger")
print(f"   - {len(utr_groups)} main settlement groups in bank statement")
print(f"   - {len(exception_payments)} expected exceptions")
print(f"   - {len(ground_truth.get('orphan_expectations', []))} orphan entries")
print(f"\n🎯 Expected Result: ~{ground_truth['metadata']['target_record_match_rate']*100:.1f}% match rate")
