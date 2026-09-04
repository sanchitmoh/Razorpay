"""Verify that fixture mode is working"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.core.razorpay_client import RazorpayClient


async def test():
    print("=" * 80)
    print(" Fixture Mode Verification")
    print("=" * 80)
    print()
    print(f"USE_FIXTURES setting: {settings.use_fixtures}")
    print()
    
    client = RazorpayClient()
    payments = await client.fetch_captured_payments()
    
    print(f"✅ Loaded {len(payments)} payment(s)")
    
    if len(payments) == 50:
        print("✅ SUCCESS! Using 50-record fixture data")
        print("\nNow refresh your browser and click 'Run Seeded 50-Record Batch'")
        print("You should see ~85% match rate!")
    elif len(payments) == 1:
        print("❌ Still using real Razorpay data (1 payment)")
        print("\nProblem: Fixture mode not working correctly")
    else:
        print(f"⚠️  Unexpected: {len(payments)} payments")
    
    print()


if __name__ == "__main__":
    asyncio.run(test())
