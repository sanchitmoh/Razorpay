"""
Test the fixed Upstash Redis EVAL format
"""

import asyncio
import os
import sys
import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings


# Token Bucket Lua script (simplified version for testing)
TOKEN_BUCKET_LUA_SCRIPT = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])

return {1, capacity}
"""


async def test_upstash_eval_formats():
    """Test different EVAL payload formats"""
    
    print("=" * 80)
    print(" Testing Upstash EVAL Formats")
    print("=" * 80)
    print()
    
    url = f"{settings.upstash_redis_rest_url.rstrip('/')}/eval"
    token = settings.upstash_redis_rest_token
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    
    # Format 1: Original (object with script, keys, args)
    print("Format 1: Object format {script, keys, args}")
    print("-" * 80)
    payload1 = {
        "script": TOKEN_BUCKET_LUA_SCRIPT,
        "keys": ["rate_limit:test"],
        "args": ["60", "1.0", "1234567890", "1"],
    }
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, headers=headers, json=payload1)
            print(f"Status: {resp.status_code}")
            print(f"Response: {resp.text[:200]}")
            if resp.status_code == 200:
                print("✅ Format 1 works!")
            else:
                print("❌ Format 1 failed")
    except Exception as e:
        print(f"❌ Exception: {e}")
    
    print()
    
    # Format 2: Array format [script, numkeys, key, ...args]
    print("Format 2: Array format [script, numkeys, key, ...args]")
    print("-" * 80)
    payload2 = [
        TOKEN_BUCKET_LUA_SCRIPT,
        "1",  # numkeys
        "rate_limit:test",
        "60", "1.0", "1234567890", "1"
    ]
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, headers=headers, json=payload2)
            print(f"Status: {resp.status_code}")
            print(f"Response: {resp.text[:200]}")
            if resp.status_code == 200:
                print("✅ Format 2 works!")
                result = resp.json().get("result")
                print(f"Result: {result}")
            else:
                print("❌ Format 2 failed")
    except Exception as e:
        print(f"❌ Exception: {e}")
    
    print()
    print("=" * 80)
    print(" Recommendation")
    print("=" * 80)
    print()
    print("If Format 2 works: The fix is correct! Restart the server.")
    print("If both fail: Upstash plan may not support Lua scripts.")
    print("             Use in-memory rate limiting (current fallback).")
    print()


if __name__ == "__main__":
    asyncio.run(test_upstash_eval_formats())
