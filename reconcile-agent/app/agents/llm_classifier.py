from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class NarrationExtraction:
    candidate_order_id: str | None
    candidate_utr: str | None
    confidence: str  # "high", "medium", "low"
    reasoning: str


class LLMClassifierAgent:
    """
    Bounded LLM classifier for unstructured narration text extraction (§5.1).
    Hard rule: LLM only returns structured evidence/candidates, NEVER writes decisions directly.
    """

    def __init__(self) -> None:
        self.openrouter_key = settings.openrouter_api_key
        self.openrouter_base_url = settings.openrouter_base_url
        self.openrouter_model = settings.openrouter_model
        self.gemini_key = settings.gemini_api_key
        self.gemini_model = settings.gemini_model
        self.timeout = settings.llm_timeout_seconds
        self.max_retries = settings.llm_max_retries

    async def extract_from_narration(
        self,
        narration: str,
        record_id: str = "unknown",
    ) -> NarrationExtraction | None:
        """
        Extracts candidate UTR and Order ID from narration text using structured LLM output.
        Fixture fallback is strictly gated behind USE_FIXTURES=1 to prevent unconfigured runs
        from fabricating synthetic matches and inflating match rates (§10).
        """
        if not narration or not narration.strip():
            return None

        # Check for local fixture fallback ONLY when explicitly enabled via USE_FIXTURES=1
        if os.getenv("USE_FIXTURES", "0") == "1":
            fixture_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "tests",
                "fixtures",
                "llm_narration_extraction_response.json",
            )
            if os.path.exists(fixture_path):
                with open(fixture_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return NarrationExtraction(
                        candidate_order_id=data.get("candidate_order_id"),
                        candidate_utr=data.get("candidate_utr"),
                        confidence=data.get("confidence", "low"),
                        reasoning=data.get("reasoning", "fixture extraction"),
                    )

        # If no LLM keys are configured, return None so records remain unextracted / UNRESOLVED_AMBIGUOUS
        if not self.openrouter_key and not self.gemini_key:
            return None

        prompt = (
            "You are a financial entity extraction assistant. Analyze the following bank narration "
            "and extract any referenced UTR (Unique Transaction Reference) or Order ID.\n"
            "Return valid JSON matching this schema:\n"
            "{\n"
            '  "candidate_order_id": string or null,\n'
            '  "candidate_utr": string or null,\n'
            '  "confidence": "high" | "medium" | "low",\n'
            '  "reasoning": string\n'
            "}\n\n"
            f"Narration: {narration}"
        )

        start_time = time.perf_counter()

        # 1. Try OpenRouter (GPT)
        if self.openrouter_key:
            for attempt in range(self.max_retries + 1):
                try:
                    from openai import AsyncOpenAI

                    client = AsyncOpenAI(
                        api_key=self.openrouter_key,
                        base_url=self.openrouter_base_url,
                        timeout=self.timeout,
                    )
                    resp = await client.chat.completions.create(
                        model=self.openrouter_model,
                        messages=[
                            {"role": "system", "content": "You are a financial text extraction model."},
                            {"role": "user", "content": prompt},
                        ],
                        response_format={"type": "json_object"},
                    )
                    content = resp.choices[0].message.content or "{}"
                    parsed = json.loads(content)
                    latency = int((time.perf_counter() - start_time) * 1000)
                    
                    logger.info(
                        "LLM extraction [record_id=%s, model=%s, latency_ms=%d, confidence=%s]",
                        record_id,
                        self.openrouter_model,
                        latency,
                        parsed.get("confidence"),
                    )
                    return NarrationExtraction(
                        candidate_order_id=parsed.get("candidate_order_id"),
                        candidate_utr=parsed.get("candidate_utr"),
                        confidence=parsed.get("confidence", "low"),
                        reasoning=parsed.get("reasoning", ""),
                    )
                except Exception as e:
                    logger.warning(
                        "OpenRouter attempt %d failed for record %s: %s",
                        attempt + 1,
                        record_id,
                        str(e),
                    )
                    if attempt < self.max_retries:
                        await asyncio.sleep(1.0)

        # 2. Try Gemini API fallback (asynchronous non-blocking call §L-6)
        if self.gemini_key:
            try:
                from google import genai
                from google.genai import types

                client = genai.Client(api_key=self.gemini_key)
                response = await client.aio.models.generate_content(
                    model=self.gemini_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                    ),
                )
                parsed = json.loads(response.text or "{}")
                latency = int((time.perf_counter() - start_time) * 1000)
                logger.info(
                    "Gemini LLM extraction [record_id=%s, model=%s, latency_ms=%d]",
                    record_id,
                    self.gemini_model,
                    latency,
                )
                return NarrationExtraction(
                    candidate_order_id=parsed.get("candidate_order_id"),
                    candidate_utr=parsed.get("candidate_utr"),
                    confidence=parsed.get("confidence", "low"),
                    reasoning=parsed.get("reasoning", ""),
                )
            except Exception as e:
                logger.warning("Gemini fallback failed for record %s: %s", record_id, str(e))

        return None
