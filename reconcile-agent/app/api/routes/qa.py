from __future__ import annotations

import html
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.qa_agent import SettlementQAAgent
from app.core.config import settings
from app.core.security import rate_limiter, verify_api_key
from app.db.database import get_db
from app.schemas.responses import APIMetadata, build_metadata_from_request

router = APIRouter(prefix="/qa", tags=["qa"])


class QARequest(BaseModel):
    question: str = Field(
        ...,
        description="Natural language question about a batch or payment discrepancy",
        max_length=4000,
    )
    batch_id: uuid.UUID | None = Field(
        default=None,
        description="Optional batch ID to ground the inquiry",
    )

    @field_validator("question")
    @classmethod
    def validate_and_sanitize_question(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Question cannot be empty or whitespace only.")
        if len(trimmed) > settings.qa_max_question_length:
            raise ValueError(
                f"Question exceeds maximum allowed length of {settings.qa_max_question_length} characters."
            )
        # HTML-escape to prevent any cross-site scripting in downstream rendering
        return html.escape(trimmed)


class QAResponse(BaseModel):
    question: str
    answer: str
    batch_id: str | None = None
    note: str | None = None
    metadata: APIMetadata | None = None


@router.post(
    "",
    response_model=QAResponse,
    dependencies=[Depends(verify_api_key), Depends(rate_limiter)],
    summary="Ask a natural language question about a reconciliation batch (§12 item 1)",
)
async def ask_batch_question(
    payload: QARequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    if not payload.question.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "BAD_REQUEST",
                    "message": "Question cannot be empty.",
                    "field": "question",
                }
            },
        )

    agent = SettlementQAAgent()
    result = await agent.answer_question(
        question=payload.question,
        batch_id=payload.batch_id,
        db=db,
    )

    meta = build_metadata_from_request(request)
    return QAResponse(
        question=result.get("question", payload.question),
        answer=result.get("answer", ""),
        batch_id=result.get("batch_id"),
        note=result.get("note"),
        metadata=meta,
    )
