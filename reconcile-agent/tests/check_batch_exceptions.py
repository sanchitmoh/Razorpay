#!/usr/bin/env python3
"""Check batch exceptions to see LLM extraction results"""
import requests
import json
import sys

if len(sys.argv) < 2:
    print("Usage: python check_batch_exceptions.py <batch_id>")
    sys.exit(1)

batch_id = sys.argv[1]

print(f"Fetching exceptions for batch: {batch_id}")
print("=" * 80)

response = requests.get(f"http://localhost:8000/api/v1/batches/{batch_id}/exceptions")

if response.ok:
    data = response.json()
    total = data.get("total", 0)
    exceptions = data.get("exceptions", [])
    
    print(f"\nTotal exceptions: {total}")
    print(f"Showing first 3 exceptions:\n")
    
    for i, ex in enumerate(exceptions[:3]):
        print(f"\n{'=' * 80}")
        print(f"EXCEPTION #{i+1}")
        print('=' * 80)
        print(json.dumps(ex, indent=2))
        
else:
    print(f"Error: {response.status_code}")
    print(response.text)
