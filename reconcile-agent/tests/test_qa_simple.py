#!/usr/bin/env python3
"""
Simple QA integration test.
Works both in pytest test runner and as standalone script: python tests/test_qa_simple.py
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_integration_qa_simple_health_and_query(client: AsyncClient):
    """Verify health endpoint and a basic QA question via in-process client."""
    health_resp = await client.get("/api/v1/health")
    assert health_resp.status_code == 200
    assert health_resp.json()["status"] in ["ok", "degraded"]

    qa_resp = await client.post(
        "/api/v1/qa",
        json={"question": "What is the status of reconciliation?"},
    )
    assert qa_resp.status_code == 200
    assert "answer" in qa_resp.json()


def run_standalone_test():
    import requests
    try:
        resp = requests.get("http://localhost:8000/api/v1/health", timeout=2)
        if resp.ok:
            qa = requests.post("http://localhost:8000/api/v1/qa", json={"question": "What is the status of reconciliation?"})
            print("Answer:", qa.json().get("answer", ""))
    except Exception as e:
        print("Error:", e)


if __name__ == "__main__":
    run_standalone_test()
