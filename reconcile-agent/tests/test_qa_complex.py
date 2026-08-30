#!/usr/bin/env python3
"""
Test QA with complex, domain-specific questions requiring deep context analysis.
Works both in pytest test runner and as standalone script: python tests/test_qa_complex.py
"""
import pytest
from httpx import AsyncClient
from app.models.batch import Batch

complex_questions = [
    {
        "question": "Analyze the reconciliation results and explain why no payments were matched. What specific data is missing and what would need to be fixed?",
        "category": "Root Cause Analysis",
    },
    {
        "question": "If I have a bank entry with UTR 'UTR20260829001', can you explain the complete reconciliation flow and where it failed in the matching stages?",
        "category": "Technical Deep Dive",
    },
    {
        "question": "What is the business impact of having exceptions in this batch? How much money is unreconciled and what actions should the finance team take?",
        "category": "Business Impact Analysis",
    },
    {
        "question": "Compare the expected amount coverage versus actual coverage. What does this tell us about the quality of our payment data and settlement process?",
        "category": "Data Quality Assessment",
    },
    {
        "question": "Walk me through what happened during the reconciliation process for this batch. Include ingestion, settlement building, matching stages, and final results.",
        "category": "Process Flow Explanation",
    },
    {
        "question": "What does the MISSING_SETTLEMENT exception mean in practical terms? How is it different from MISSING_BANK_ENTRY, and what caused it in this batch?",
        "category": "Exception Interpretation",
    },
    {
        "question": "If we want to fix this batch and get matches, what specific steps should we take? Be concrete about what data needs to be added or corrected.",
        "category": "Remediation Plan",
    },
]


@pytest.mark.asyncio
async def test_integration_qa_complex_domain_questions(client: AsyncClient, seeded_batch: Batch):
    """Test all 7 complex domain analysis questions against a seeded batch in-process."""
    for item in complex_questions:
        q = item["question"]
        resp = await client.post(
            "/api/v1/qa",
            json={
                "question": q,
                "batch_id": str(seeded_batch.id),
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "answer" in data
        assert len(data["answer"]) > 20
        assert "metadata" in data
        assert data["metadata"]["request_id"] is not None


def run_standalone_test():
    import requests
    server_url = "http://localhost:8000"
    for item in complex_questions:
        try:
            r = requests.post(f"{server_url}/api/v1/qa", json={"question": item["question"]})
            if r.ok:
                print(f"[{item['category']}] Answer length:", len(r.json().get("answer", "")))
        except Exception as e:
            print("Error:", e)


if __name__ == "__main__":
    run_standalone_test()
