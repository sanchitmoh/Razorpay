"""
Enhanced Test Payment Creation Script for Razorpay

NOTE: Razorpay API cannot automatically capture payments in test mode without
a real payment flow. This script provides two approaches:

Approach 1: Create orders and provide payment links (manual capture via dashboard)
Approach 2: Use the synthetic data generator for fully automated testing
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


async def create_orders_with_instructions():
    """
    Creates test orders in Razorpay and provides instructions for manual payment capture.
    
    Why manual capture is needed:
    - Razorpay API requires a real payment flow (customer checkout) to capture payments
    - You cannot programmatically "fake" a payment capture via API
    - Test mode still requires simulating the customer payment journey
    """
    key_id = settings.razorpay_key_id
    key_secret = settings.razorpay_key_secret

    print("=" * 80)
    print(" Razorpay Test Payment Creator")
    print("=" * 80)

    if not key_id or not key_secret:
        print("\n❌ RAZORPAY_KEY_ID or RAZORPAY_KEY_SECRET is not set in .env")
        print("\nAdd them to your .env file:")
        print("   RAZORPAY_KEY_ID=rzp_test_YourKeyHere")
        print("   RAZORPAY_KEY_SECRET=YourSecretHere\n")
        return

    client = RazorpayClient(key_id=key_id, key_secret=key_secret)
    print(f"\n🔗 Connected to Razorpay API: {key_id[:12]}...")

    # Create test orders
    print("\n📦 Creating 10 test orders...")
    orders = []
    
    for i in range(1, 11):
        amount = (i * 100 + 500) * 100  # ₹600, ₹700, ₹800, etc. in paise
        receipt = f"test_order_{int(datetime.now().timestamp())}_{i:02d}"
        
        try:
            order = await client.create_order(
                amount_paise=amount,
                receipt=receipt,
                notes={"batch": "test_payments", "index": str(i)},
            )
            orders.append(order)
            print(f"   ✅ Order {i:2d}: {order['id']} | ₹{amount/100:.2f} | {receipt}")
        except Exception as e:
            print(f"   ❌ Order {i} failed: {e}")

    if not orders:
        print("\n❌ No orders were created. Check your API credentials.")
        return

    print(f"\n✅ Created {len(orders)} test orders successfully!")
    
    # Provide instructions for capturing payments
    print("\n" + "=" * 80)
    print(" 🎯 NEXT STEPS: How to Capture These Payments")
    print("=" * 80)
    
    print("\n📌 METHOD 1: Using Razorpay Dashboard (Easiest)")
    print("-" * 80)
    print("1. Go to: https://dashboard.razorpay.com/app/orders")
    print("2. Make sure you're in TEST MODE (toggle at top-right)")
    print("3. You'll see the orders listed above")
    print("4. For each order, you need to simulate a payment:")
    print("   - Click on the order")
    print("   - Use Razorpay's test checkout")
    print("   - Test Card Number: 4111 1111 1111 1111")
    print("   - CVV: Any 3 digits (e.g., 123)")
    print("   - Expiry: Any future date (e.g., 12/25)")
    print("   - Name: Any name")
    print("5. After payment, the order status will change to 'Paid'")
    
    print("\n📌 METHOD 2: Using Payment Links (Faster)")
    print("-" * 80)
    print("You can create payment links for quick testing:")
    print("1. Go to: https://dashboard.razorpay.com/app/payment-links")
    print("2. Click 'Create Payment Link'")
    print("3. Enter amount and customer details")
    print("4. Copy the link and open it in a browser")
    print("5. Use test card: 4111 1111 1111 1111")
    
    print("\n📌 METHOD 3: Use Synthetic Data (Recommended for Testing)")
    print("-" * 80)
    print("For automated testing without manual steps:")
    print("   cd \"c:\\class project\\Razorpay\\reconcile-agent\"")
    print("   python scripts/generate_synthetic_data.py")
    print("\nThis generates 50 fully-captured test payments with:")
    print("   ✅ Complete payment records")
    print("   ✅ Matching bank statements")
    print("   ✅ Aligned ledger entries")
    print("   ✅ Known ground truth for validation")
    
    print("\n📌 METHOD 4: Integration Testing (Advanced)")
    print("-" * 80)
    print("Build a test checkout page that uses Razorpay.js to simulate real payments.")
    print("See: https://razorpay.com/docs/payments/payment-gateway/web-integration/standard/")
    
    print("\n" + "=" * 80)
    print(" ⏳ After Capturing Payments")
    print("=" * 80)
    print("\n1. Verify captured payments:")
    print("   https://dashboard.razorpay.com/app/payments")
    print("\n2. Fetch them via this script:")
    print("   python scripts/fetch_and_sync_payments.py")
    print("\n3. Run reconciliation:")
    print("   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload")
    print("   Open: http://localhost:8000")
    
    print("\n" + "=" * 80)
    print(" 💡 Quick Tip")
    print("=" * 80)
    print("\nFor immediate testing, use METHOD 3 (synthetic data):")
    print("   python scripts/generate_synthetic_data.py")
    print("   uvicorn app.main:app --reload")
    print("   Click 'Run Seeded 50-Record Batch' on http://localhost:8000\n")


async def fetch_existing_payments():
    """
    Fetches any existing captured payments from your Razorpay test account
    and generates corresponding CSV files.
    """
    key_id = settings.razorpay_key_id
    key_secret = settings.razorpay_key_secret

    if not key_id or not key_secret:
        print("\n❌ Razorpay credentials not configured in .env")
        return

    client = RazorpayClient(key_id=key_id, key_secret=key_secret)
    
    print("\n🔍 Fetching captured payments from Razorpay...")
    
    try:
        payments = await client.fetch_captured_payments(use_fixture_fallback=False)
        
        if not payments:
            print("\n⚠️  No captured payments found in your test account.")
            print("\nTo get started:")
            print("1. Create and capture payments using the instructions above, OR")
            print("2. Run: python scripts/generate_synthetic_data.py\n")
            return
        
        print(f"✅ Found {len(payments)} captured payment(s)")
        
        # Generate CSV files
        print("\n💾 Generating CSV files from captured payments...")
        
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
                writer.writerow([
                    p.get("order_id") or f"ord_{p['id']}",
                    p["amount"],
                    p.get("email") or f"customer_{p['id'][:8]}",
                    date.today().isoformat(),
                ])

        # Group payments by day for bank settlements
        daily_groups = defaultdict(list)
        for p in payments:
            created_ts = p.get("created_at") or int(datetime.now().timestamp())
            p_date = datetime.fromtimestamp(created_ts, tz=timezone.utc).date()
            daily_groups[p_date].append(p)

        # Write Bank Statement CSV
        with open(bank_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["utr", "amount_paise", "value_date", "narration"])
            for p_date, day_pays in daily_groups.items():
                gross = sum(p["amount"] for p in day_pays)
                fee = sum(p.get("fee", 0) or int(p["amount"] * 0.02) for p in day_pays)
                tax = sum(p.get("tax", 0) or int(fee * 0.18) for p in day_pays)
                net = gross - fee - tax
                utr = f"UTR{p_date.strftime('%Y%m%d')}001"
                narration = f"Razorpay Settlement {utr} - {len(day_pays)} payments"
                writer.writerow([utr, net, p_date.isoformat(), narration])

        print(f"   ✅ Ledger CSV: {ledger_path}")
        print(f"   ✅ Bank CSV: {bank_path}")
        print("\n🎉 CSV files generated! Ready for reconciliation.")
        print(f"\nTotal payments: {len(payments)}")
        print(f"Total settlement days: {len(daily_groups)}")
        
    except Exception as e:
        print(f"\n❌ Error fetching payments: {e}")


async def main():
    """Main entry point - provides options for the user"""
    print("\n" + "=" * 80)
    print(" Razorpay Test Payment Helper")
    print("=" * 80)
    print("\nWhat would you like to do?")
    print("\n1. Create new test orders (you'll need to manually capture them)")
    print("2. Fetch existing captured payments and generate CSVs")
    print("3. See instructions for automated testing")
    print("\nEnter your choice (1-3): ", end="")
    
    # For script automation, default to option 1
    choice = "1"
    
    print(choice)
    
    if choice == "1":
        await create_orders_with_instructions()
    elif choice == "2":
        await fetch_existing_payments()
    elif choice == "3":
        print("\n📚 AUTOMATED TESTING APPROACH (Recommended)")
        print("=" * 80)
        print("\nFor full automated testing without manual payment capture:")
        print("\n   cd \"c:\\class project\\Razorpay\\reconcile-agent\"")
        print("   python scripts/generate_synthetic_data.py")
        print("\nThis creates a complete test dataset with 50 payments.")
        print("\nThen start the server:")
        print("   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload")
        print("\nOpen http://localhost:8000 and click 'Run Seeded 50-Record Batch'")
    
    # Also try to fetch any existing payments
    print("\n" + "=" * 80)
    await fetch_existing_payments()


if __name__ == "__main__":
    asyncio.run(main())
