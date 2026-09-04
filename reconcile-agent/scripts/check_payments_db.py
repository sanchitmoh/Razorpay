"""Check how many payments are in the database"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.database import get_session
from app.db.models import Payment
from sqlalchemy import select


async def check_payments():
    async with get_session() as session:
        result = await session.execute(select(Payment))
        payments = result.scalars().all()
        
        print(f"Total payments in database: {len(payments)}")
        
        if payments:
            print("\nPayments found:")
            for p in payments[:10]:  # Show first 10
                print(f"  - {p.id} | Order: {p.order_id} | Amount: Rs {p.amount_paise/100}")
        else:
            print("\n⚠️  NO PAYMENTS IN DATABASE!")
            print("\nThis is why reconciliation shows 0% match.")
            print("\nThe system needs Razorpay payment data to match against.")
            print("\nSolution:")
            print("  1. Fetch real payments: python scripts/fetch_and_sync_payments.py")
            print("  2. Or populate with test data from fixtures")


if __name__ == "__main__":
    asyncio.run(check_payments())
