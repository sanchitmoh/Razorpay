"""
Test Upstash Redis connection and diagnose HTTP 400 errors
"""

import asyncio
import os
import sys
import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings


async def test_upstash_connection():
    """Test Upstash Redis REST API connection"""
    
    print("=" * 80)
    print(" Upstash Redis Connection Test")
    print("=" * 80)
    
    url = settings.upstash_redis_rest_url
    token = settings.upstash_redis_rest_token
    
    if not url or not token:
        print("\n❌ Upstash Redis credentials not configured")
        print("\nSet these in .env:")
        print("   UPSTASH_REDIS_REST_URL=https://...upstash.io")
        print("   UPSTASH_REDIS_REST_TOKEN=...")
        return
    
    print(f"\n📡 Testing connection to: {url}")
    print(f"🔑 Token: {token[:20]}..." if len(token) > 20 else f"🔑 Token: {token}")
    print()
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # Test 1: PING command
    print("Test 1: PING command")
    print("-" * 80)
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{url}/ping", headers=headers)
            
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.text}")
            
            if response.status_code == 200:
                print("✅ PING successful!")
            else:
                print(f"❌ PING failed with status {response.status_code}")
                print(f"Error: {response.text}")
    
    except Exception as e:
        print(f"❌ Exception during PING: {e}")
    
    print()
    
    # Test 2: GET command (similar to what rate limiter uses)
    print("Test 2: GET command (rate limiter simulation)")
    print("-" * 80)
    
    test_key = "test:rate_limit:check"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{url}/get/{test_key}", headers=headers)
            
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.text}")
            
            if response.status_code in (200, 404):  # 404 is OK (key doesn't exist)
                print("✅ GET command successful!")
            else:
                print(f"❌ GET failed with status {response.status_code}")
    
    except Exception as e:
        print(f"❌ Exception during GET: {e}")
    
    print()
    
    # Test 3: SET command
    print("Test 3: SET command")
    print("-" * 80)
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{url}/set/{test_key}",
                headers=headers,
                json={"value": "test_value", "ex": 60}
            )
            
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.text}")
            
            if response.status_code == 200:
                print("✅ SET command successful!")
            else:
                print(f"❌ SET failed with status {response.status_code}")
    
    except Exception as e:
        print(f"❌ Exception during SET: {e}")
    
    print()
    
    # Test 4: EVAL command (used by rate limiter for atomic operations)
    print("Test 4: EVAL command (Token Bucket Lua script)")
    print("-" * 80)
    
    lua_script = """
    local key = KEYS[1]
    local capacity = tonumber(ARGV[1])
    return capacity
    """
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{url}/eval",
                headers=headers,
                json={
                    "script": lua_script,
                    "keys": ["test:bucket"],
                    "args": ["60"]
                }
            )
            
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.text}")
            
            if response.status_code == 200:
                print("✅ EVAL command successful!")
            else:
                print(f"❌ EVAL failed with status {response.status_code}")
                print("\n⚠️  This is likely why rate limiting is failing!")
                print("Upstash may not support EVAL or the script format is wrong.")
    
    except Exception as e:
        print(f"❌ Exception during EVAL: {e}")
    
    print()
    print("=" * 80)
    print(" Diagnosis Summary")
    print("=" * 80)
    print()
    print("If PING works but EVAL fails:")
    print("  → Upstash database may not support Lua scripts")
    print("  → Check your Upstash plan (some plans restrict scripting)")
    print("  → Solution: Use in-memory rate limiting (current fallback)")
    print()
    print("If PING fails:")
    print("  → Token or URL is invalid")
    print("  → Regenerate credentials at: https://console.upstash.com/")
    print()
    print("Current behavior: System gracefully falls back to in-memory")
    print("                  rate limiting, which works fine for dev/test.")
    print()


if __name__ == "__main__":
    asyncio.run(test_upstash_connection())
