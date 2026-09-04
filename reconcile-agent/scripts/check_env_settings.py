"""Check if environment settings are loaded correctly"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings

print("=" * 80)
print(" Environment Settings Check")
print("=" * 80)
print()
print(f"USE_FIXTURES env var: {os.getenv('USE_FIXTURES')}")
print(f"settings object value: {settings.use_fixtures}")
print()
print(f"USE_FIXTURES == '1': {os.getenv('USE_FIXTURES') == '1'}")
print()

if os.getenv('USE_FIXTURES') == '1':
    print("✅ Fixture mode is ENABLED")
    print("   System will use 50-record test fixtures")
else:
    print("❌ Fixture mode is DISABLED")  
    print("   System will fetch real Razorpay payments")
print()
