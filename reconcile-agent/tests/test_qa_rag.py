#!/usr/bin/env python3
"""
Test the RAG/QA feature to verify grounding and response synthesis.
Works both in pytest test runner and as standalone script: python tests/test_qa_rag.py
"""
import pytest
from httpx import AsyncClient
from app.models.batch import Batch


@pytest.mark.asyncio
async def test_integration_qa_rag_general_question(client: AsyncClient):
    """Test QA endpoint with a general query without specific batch."""
    response = await client.post(
        "/api/v1/qa",
        json={"question": "What is the overall status of reconciliation?"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert len(data["answer"]) > 0
    assert "metadata" in data
    assert data["metadata"]["request_id"] is not None


@pytest.mark.asyncio
async def test_integration_qa_rag_batch_specific(client: AsyncClient, seeded_batch: Batch):
    """Test QA endpoint with a specific batch ID and grounded context."""
    questions = [
        "Why did this batch have exceptions?",
        "What was the match rate for this batch?",
        "Explain the reconciliation results",
    ]
    for question in questions:
        response = await client.post(
            "/api/v1/qa",
            json={
                "question": question,
                "batch_id": str(seeded_batch.id),
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "answer" in data
        assert len(data["answer"]) > 0
        assert data["batch_id"] == str(seeded_batch.id)


def run_standalone_test():
    import requests
    try:
        resp = requests.get("http://localhost:8000/api/v1/health", timeout=2)
        if resp.ok:
            qa_resp = requests.post(
                "http://localhost:8000/api/v1/qa",
                json={"question": "What is the overall status of reconciliation?"},
            )
            print("Answer:", qa_resp.json().get("answer", ""))
        else:
            print("Server not accessible")
    except Exception as e:
        print("Error:", e)


if __name__ == "__main__":
    run_standalone_test()
