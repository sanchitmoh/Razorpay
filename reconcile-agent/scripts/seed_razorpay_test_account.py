from __future__ import annotations

import asyncio
import csv
import os
import sys
from datetime import date, datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.core.razorpay_client import RazorpayClient


async def seed_live_test_account():
    """
    Utility script to interact with your live Razorpay test-mode account:
      1. Verifies credentials from .env (RAZORPAY_KEY_ID & RAZORPAY_KEY_SECRET).
      2. Creates a batch of test orders in your Razorpay Dashboard.
      3. Pulls your captured payments from Razorpay's live test API.
      4. Automatically constructs aligned Bank Statement & Ledger CSV files in data/.
    """
    key_id = settings.razorpay_key_id
    key_secret = settings.razorpay_key_secret

    print("=" * 70)
    print(" Razorpay Test-Mode Account Seeder & Live Synchronizer")
    print("=" * 70)

    if not key_id or not key_secret:
        print("\n[!] RAZORPAY_KEY_ID or RAZORPAY_KEY_SECRET is not set in your .env file.")
        print("    Please add them to .env:")
        print("    RAZORPAY_KEY_ID=rzp_test_YourKeyHere")
        print("    RAZORPAY_KEY_SECRET=YourSecretHere\n")
        return

    client = RazorpayClient(key_id=key_id, key_secret=key_secret)
    print(f"[*] Connecting to Razorpay API with Key ID: {key_id[:8]}***")

    # Step 1: Create 5 sample test orders in live test mode
    print("\n[*] Step 1: Creating sample test orders in Razorpay test mode...")
    sample_orders = []
    for i in range(1, 6):
        amount = (i * 500 + 1000) * 100  # ₹1500, ₹2000, etc. in paise
        receipt = f"live_rcpt_{int(datetime.now().timestamp())}_{i:02d}"
        try:
            order = await client.create_order(
                amount_paise=amount,
                receipt=receipt,
                notes={"batch": "reconciliation_live_demo", "index": str(i)},
            )
            sample_orders.append(order)
            print(f"    [+] Created Order: {order['id']} | Amount: ₹{amount/100:.2f} | Receipt: {receipt}")
        except Exception as e:
            print(f"    [-] Order creation failed: {e}")

    # Step 2: Fetch all captured test payments from your account
    print("\n[*] Step 2: Fetching captured payments from your Razorpay test dashboard...")
    try:
        payments = await client.fetch_captured_payments(use_fixture_fallback=False)
        print(f"    [+] Successfully fetched {len(payments)} captured payment(s) from Razorpay.")
    except Exception as e:
        print(f"    [-] Error fetching payments: {e}")
        return

    if not payments:
        print("\n[!] No captured payments found in your test account yet.")
        print("    Tip: You can capture test payments from the Razorpay Dashboard or")
        print("    run the included offline synthetic dataset generator with:")
        print("    python scripts/generate_synthetic_data.py")
        return

    # Step 3: Build aligned Bank Statement and Ledger CSVs
    print("\n[*] Step 3: Synchronizing live payments to Bank Statement & Ledger CSVs...")
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(base_dir, "data")
    os.makedirs(data_dir, exist_ok=True)

    ledger_path = os.path.join(data_dir, "synthetic_ledger.csv")
    bank_path = os.path.join(data_dir, "synthetic_bank_statement.csv")

    # Write Ledger CSV
    with open(ledger_path, "w", newline="", encoding="utf-8") as f_ledger:
        writer = csv.writer(f_ledger)
        writer.writerow(["order_id", "expected_amount_paise", "customer_ref", "invoice_date"])
        for p in payments:
            writer.writerow([
                p.get("order_id") or f"ord_{p['id']}",
                p["amount"],
                p.get("email") or f"cust_{p['id']}",
                date.today().isoformat(),
            ])

    # Group payments by day to build bank settlement entries (§3 daily grouping rule)
    from collections import defaultdict
    daily_groups = defaultdict(list)
    for p in payments:
        created_ts = p.get("created_at") or int(datetime.now().timestamp())
        p_date = datetime.fromtimestamp(created_ts, tz=timezone.utc).date()
        daily_groups[p_date].append(p)

    with open(bank_path, "w", newline="", encoding="utf-8") as f_bank:
        writer = csv.writer(f_bank)
        writer.writerow(["utr", "amount_paise", "value_date", "narration"])
        for p_date, day_pays in daily_groups.items():
            gross = sum(p["amount"] for p in day_pays)
            fee = sum(p.get("fee") or int(p["amount"] * 0.02) for p in day_pays)
            tax = sum(p.get("tax") or int(fee * 0.18) for p in day_pays)
            net = gross - fee - tax
            utr = f"UTR{p_date.strftime('%Y%m%d')}001"
            writer.writerow([utr, net, p_date.isoformat(), f"Razorpay Live Test Settlement {utr}"])

    print(f"    [+] Saved Ledger CSV: {ledger_path}")
    print(f"    [+] Saved Bank Statement CSV: {bank_path}")
    print("\n[✓] Live synchronization complete! You can now run reconciliation against your real account.")


if __name__ == "__main__":
    asyncio.run(seed_live_test_account())
