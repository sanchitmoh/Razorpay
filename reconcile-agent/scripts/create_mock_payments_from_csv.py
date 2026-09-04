"""
Create mock Razorpay payments JSON fixture from your bank and ledger CSV files.
This allows you to test reconciliation with your own CSV data without needing
real Razorpay payments.

Usage:
  python create_mock_payments_from_csv.py path/to/bank.csv path/to/ledger.csv
"""

import csv
import json
import sys
from datetime import datetime
from collections import defaultdict


def create_mock_payments(bank_csv_path, ledger_csv_path):
    """Generate mock Razorpay payments from CSV files"""
    
    print("=" * 80)
    print(" Creating Mock Razorpay Payments from CSV Files")
    print("=" * 80)
    print()
    
    # Read ledger to get order IDs and amounts
    ledger_entries = []
    print(f"Reading ledger: {ledger_csv_path}")
    
    try:
        with open(ledger_csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                ledger_entries.append({
                    'order_id': row.get('order_id', ''),
                    'amount': int(row.get('expected_amount_paise', 0)),
                    'date': row.get('invoice_date', datetime.now().strftime('%Y-%m-%d'))
                })
        print(f"✅ Loaded {len(ledger_entries)} ledger entries")
    except Exception as e:
        print(f"❌ Error reading ledger: {e}")
        return
    
    # Read bank to get settlement info
    bank_entries = []
    print(f"\nReading bank statement: {bank_csv_path}")
    
    try:
        with open(bank_csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                bank_entries.append({
                    'utr': row.get('utr', ''),
                    'amount': int(row.get('amount_paise', 0)),
                    'date': row.get('value_date', datetime.now().strftime('%Y-%m-%d'))
                })
        print(f"✅ Loaded {len(bank_entries)} bank entries")
    except Exception as e:
        print(f"❌ Error reading bank: {e}")
        return
    
    # Generate mock payments
    print("\n📦 Generating mock Razorpay payments...")
    
    mock_payments = []
    for i, entry in enumerate(ledger_entries, 1):
        payment_id = f"pay_mock_{i:04d}"
        order_id = entry['order_id'] or f"order_mock_{i:04d}"
        amount = entry['amount']
        
        # Parse date
        try:
            date_obj = datetime.strptime(entry['date'], '%Y-%m-%d')
            created_at = int(date_obj.timestamp())
        except:
            created_at = int(datetime.now().timestamp())
        
        # Calculate fees (2% of amount + 18% GST)
        fee = int(amount * 0.02)
        tax = int(fee * 0.18)
        
        payment = {
            "id": payment_id,
            "entity": "payment",
            "amount": amount,
            "currency": "INR",
            "status": "captured",
            "order_id": order_id,
            "method": "card",
            "captured": True,
            "fee": fee,
            "tax": tax,
            "email": f"customer{i}@example.com",
            "contact": "+919999999999",
            "created_at": created_at,
            "captured_at": created_at
        }
        
        mock_payments.append(payment)
    
    # Save to fixture file
    fixture_path = "tests/fixtures/razorpay_payments_custom.json"
    fixture_data = {
        "entity": "collection",
        "count": len(mock_payments),
        "items": mock_payments
    }
    
    print(f"\n💾 Saving {len(mock_payments)} mock payments to: {fixture_path}")
    
    with open(fixture_path, 'w', encoding='utf-8') as f:
        json.dump(fixture_data, f, indent=2)
    
    print("✅ Mock payments created!")
    
    print("\n" + "=" * 80)
    print(" Next Steps")
    print("=" * 80)
    print("\n1. The system needs to load this custom fixture file")
    print("2. Update RazorpayClient to use 'razorpay_payments_custom.json'")
    print("3. Set USE_FIXTURES=1 in .env")
    print("4. Restart server and upload your CSV files")
    print("\nOr use the simpler approach:")
    print("   Just use the built-in synthetic data for demo purposes!")
    print()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python create_mock_payments_from_csv.py <bank.csv> <ledger.csv>")
        sys.exit(1)
    
    bank_csv = sys.argv[1]
    ledger_csv = sys.argv[2]
    
    create_mock_payments(bank_csv, ledger_csv)
