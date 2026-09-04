#!/usr/bin/env python3
"""Generate matching CSV fixtures from the 50-payment fixture JSON"""

import json
import csv
from datetime import date, datetime, timezone
from collections import defaultdict
import os

# Paths
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fixtures_dir = os.path.join(base_dir, "tests", "fixtures")
fixture_json = os.path.join(fixtures_dir, "razorpay_payments_50_mixed.json")

# Load fixture payments
with open(fixture_json, 'r', encoding='utf-8') as f:
    data = json.load(f)
    payments = data.get('items', [])

print(f"Loaded {len(payments)} payments from fixture")

# Generate matching ledger CSV
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

# Generate matching bank statement CSV (grouped by date, with settlements)
daily_groups = defaultdict(list)
for p in payments:
    created_ts = p.get('created_at', int(datetime.now().timestamp()))
    p_date = datetime.fromtimestamp(created_ts, tz=timezone.utc).date()
    daily_groups[p_date].append(p)

bank_path = os.path.join(fixtures_dir, "fixture_bank_statement_50.csv")
with open(bank_path, 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow(['utr', 'amount_paise', 'value_date', 'narration'])
    for p_date, day_pays in sorted(daily_groups.items()):
        gross = sum(p['amount'] for p in day_pays)
        fee = sum(p.get('fee', int(p['amount'] * 0.02)) for p in day_pays)
        tax = sum(p.get('tax', int(fee * 0.18)) for p in day_pays)
        net = gross - fee - tax
        utr = f'UTR{p_date.strftime("%Y%m%d")}001'
        writer.writerow([utr, net, p_date.isoformat(), f'Razorpay Settlement {utr}'])

print(f"✅ Created {bank_path}")
print(f"\n📋 Summary:")
print(f"   - {len(payments)} payments in ledger")
print(f"   - {len(daily_groups)} settlement groups in bank statement")
print(f"\n🎯 Next: Upload these CSVs when clicking 'Run Seeded 50-Record Batch'")
