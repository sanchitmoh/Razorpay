"""Test the correct Upstash REST API format"""

import asyncio
import httpx
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings

TOKEN_BUCKET_LUA_SCRIPT = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])
return {1, capacity}
"""

async def test():
    url = settings.upstash_redis_rest_url.rstrip('/')
    headers = {
        "Authorization": f"Bearer {settings.upstash_redis_rest_token}",
        "Content-Type": "application/json",
    }
    
    # Correct format from Upstash docs
    payload = [
        "EVAL",
        TOKEN_BUCKET_LUA_SCRIPT,
        "1",  # numkeys
        "rate_limit:test",
        "60", "1.0", "1234567890", "1"
    ]
    
    print("Testing Upstash EVAL with correct format...")
    print(f"URL: {url}")
    print()
    
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        print(f"Status: {resp.status_code}")
        print(f"Response: {resp.text}")
        
        if resp.status_code == 200:
            print("\n✅ SUCCESS! Upstash Redis is working!")
            result = resp.json().get("result")
            print(f"Result: {result}")
        else:
            print("\n❌ FAILED")

if __name__ == "__main__":
    asyncio.run(test())
