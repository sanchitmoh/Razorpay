#!/usr/bin/env python3
"""Test the new seeded batch endpoint"""

import requests

print("Testing /api/v1/batches/seeded endpoint...")
print("=" * 70)

resp = requests.post('http://localhost:8000/api/v1/batches/seeded')

if resp.ok:
    data = resp.json()
    print(f"✅ Status: {resp.status_code} OK")
    print(f"\n📊 Results:")
    print(f"   Total Records: {data['total_records']}")
    print(f"   Matched: {data['matched_records']}")
    print(f"   Exceptions: {data['exception_count']}")
    print(f"   Match Rate: {data['record_match_rate']*100:.1f}%")
    print(f"   Amount Coverage: {data['amount_coverage']*100:.1f}%")
    print(f"\n🔗 Batch ID: {data['batch_id']}")
    print(f"🌐 View at: http://localhost:8000/batch/{data['batch_id']}")
    
    if data['exception_count'] > 0:
        print(f"\n⚠️ Exception Breakdown:")
        for reason, count in data.get('reason_code_breakdown', {}).items():
            print(f"   - {reason}: {count}")
else:
    print(f"❌ Error {resp.status_code}:")
    print(resp.text)
