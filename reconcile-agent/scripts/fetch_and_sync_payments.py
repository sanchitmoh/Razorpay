"""
Fetch existing captured payments from Razorpay and generate CSV files.

This script is useful when you've manually captured payments through the dashboard
and want to sync them to CSV files for reconciliation.
"""

from __future__ import annotations

import asyncio
import csv
import os
import sys
from datetime import date, datetime, timezone
from collections import defaultdict

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.core.razorpay_client import RazorpayClient


async def fetch_and_sync():
    """Fetch captured payments and generate CSV files"""
    
    key_id = settings.razorpay_key_id
    key_secret = settings.razorpay_key_secret

    print("=" * 80)
    print(" Razorpay Payment Sync - Fetch & Generate CSVs")
    print("=" * 80)

    if not key_id or not key_secret:
        print("\n❌ RAZORPAY_KEY_ID or RAZORPAY_KEY_SECRET not set in .env")
        print("\nAdd credentials to your .env file:")
        print("   RAZORPAY_KEY_ID=rzp_test_YourKeyHere")
        print("   RAZORPAY_KEY_SECRET=YourSecretHere\n")
        return

    client = RazorpayClient(key_id=key_id, key_secret=key_secret)
    print(f"\n🔗 Connected: {key_id[:12]}...")
    
    print("\n🔍 Fetching captured payments from Razorpay test account...")
    
    try:
        payments = await client.fetch_captured_payments(use_fixture_fallback=False)
        
        if not payments:
            print("\n⚠️  No captured payments found!")
            print("\n📌 To create captured payments:")
            print("\n   Option 1: Manual Dashboard Capture")
            print("   1. Go to https://dashboard.razorpay.com/app/orders")
            print("   2. Make sure TEST MODE is enabled")
            print("   3. Create an order")
            print("   4. Complete payment with test card: 4111 1111 1111 1111")
            print("\n   Option 2: Use Synthetic Data (Recommended)")
            print("   Run: python scripts/generate_synthetic_data.py\n")
            return
        
        print(f"✅ Found {len(payments)} captured payment(s)\n")
        
        # Display payment summary
        total_amount = sum(p["amount"] for p in payments)
        print(f"💰 Total Amount: ₹{total_amount/100:,.2f}")
        print(f"📅 Payments:")
        for i, p in enumerate(payments[:10], 1):  # Show first 10
            print(f"   {i}. {p['id']} | ₹{p['amount']/100:.2f} | {p.get('order_id', 'N/A')}")
        if len(payments) > 10:
            print(f"   ... and {len(payments) - 10} more")
        
        # Generate CSV files
        print("\n💾 Generating CSV files...")
        
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        data_dir = os.path.join(base_dir, "data")
        os.makedirs(data_dir, exist_ok=True)

        ledger_path = os.path.join(data_dir, "live_ledger.csv")
        bank_path = os.path.join(data_dir, "live_bank_statement.csv")

        # Write Ledger CSV
        with open(ledger_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["order_id", "expected_amount_paise", "customer_ref", "invoice_date"])
            for p in payments:
                order_id = p.get("order_id") or f"order_{p['id']}"
                customer = p.get("email") or p.get("contact") or f"customer_{p['id'][:8]}"
                writer.writerow([
                    order_id,
                    p["amount"],
                    customer,
                    date.today().isoformat(),
                ])

        # Group payments by settlement date (daily)
        daily_groups = defaultdict(list)
        for p in payments:
            created_ts = p.get("created_at") or int(datetime.now().timestamp())
            p_date = datetime.fromtimestamp(created_ts, tz=timezone.utc).date()
            daily_groups[p_date].append(p)

        # Write Bank Statement CSV
        with open(bank_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["utr", "amount_paise", "value_date", "narration"])
            
            for p_date, day_pays in sorted(daily_groups.items()):
                # Calculate settlement amount (gross - fees - tax)
                gross = sum(p["amount"] for p in day_pays)
                # Estimate fees at 2% if not provided
                fee = sum(p.get("fee", 0) or int(p["amount"] * 0.02) for p in day_pays)
                # GST at 18% on fees
                tax = sum(p.get("tax", 0) or int(fee * 0.18) for p in day_pays)
                net = gross - fee - tax
                
                utr = f"UTR{p_date.strftime('%Y%m%d')}001"
                narration = f"Razorpay Settlement {utr} - {len(day_pays)} payment(s)"
                writer.writerow([utr, net, p_date.isoformat(), narration])

        print(f"   ✅ Ledger: {ledger_path}")
        print(f"   ✅ Bank:   {bank_path}")
        print(f"\n📊 Summary:")
        print(f"   • {len(payments)} payments processed")
        print(f"   • {len(daily_groups)} settlement day(s)")
        print(f"   • Total: ₹{total_amount/100:,.2f}")
        
        print("\n" + "=" * 80)
        print(" 🎉 Success! CSV files generated.")
        print("=" * 80)
        print("\n📌 Next Steps:")
        print("\n1. Start the reconciliation server:")
        print("   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload")
        print("\n2. Open http://localhost:8000")
        print("\n3. Upload the generated CSV files:")
        print(f"   • Bank Statement: {bank_path}")
        print(f"   • Ledger:         {ledger_path}")
        print("\n4. Run reconciliation and view results!\n")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\nTroubleshooting:")
        print("1. Verify your API credentials in .env")
        print("2. Make sure you're in TEST MODE on Razorpay dashboard")
        print("3. Check if you have captured payments at:")
        print("   https://dashboard.razorpay.com/app/payments\n")


if __name__ == "__main__":
    asyncio.run(fetch_and_sync())
