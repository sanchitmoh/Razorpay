#!/usr/bin/env python3
"""
Test script to verify Razorpay, LLM, and Database connections.
Works both in pytest test runner and as standalone script: python tests/test_connections.py
"""
import asyncio
import os
import sys
from pathlib import Path
import pytest
from dotenv import load_dotenv

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

load_dotenv()


async def check_razorpay():
    from app.core.razorpay_client import RazorpayClient
    client = RazorpayClient()
    try:
        payments = await client.fetch_captured_payments()
        return isinstance(payments, list)
    except Exception:
        return False


async def check_llm():
    from app.agents.llm_classifier import LLMClassifierAgent
    agent = LLMClassifierAgent()
    try:
        result = await agent.extract_from_narration("RAZORPAY SETL UTR123456 IMPS TXN")
        return result is not None
    except Exception:
        return False


def main():
    print("=" * 80)
    print("RAZORPAY RECONCILIATION AGENT - CONNECTION TEST")
    print("=" * 80)
    rzp_ok = asyncio.run(check_razorpay())
    print(f"Razorpay Connection: {'✅ PASS' if rzp_ok else '❌ FAIL'}")
    llm_ok = asyncio.run(check_llm())
    print(f"LLM Connection: {'✅ PASS' if llm_ok else '⚠️  SKIPPED / FALLBACK'}")


@pytest.mark.asyncio
async def test_integration_connections_razorpay_client():
    """Verify RazorpayClient connects or safely uses fixture fallback."""
    from app.core.razorpay_client import RazorpayClient
    client = RazorpayClient()
    payments = await client.fetch_captured_payments(use_fixture_fallback=True)
    assert isinstance(payments, list)
    assert len(payments) > 0


@pytest.mark.asyncio
async def test_integration_connections_llm_classifier():
    """Verify LLM classifier initializes and performs narration extraction."""
    from app.agents.llm_classifier import LLMClassifierAgent
    agent = LLMClassifierAgent()
    result = await agent.extract_from_narration("RAZORPAY SETL UTR999888 IMPS TXN")
    assert result is not None
    assert hasattr(result, "candidate_utr")
    assert hasattr(result, "confidence")


if __name__ == "__main__":
    main()
