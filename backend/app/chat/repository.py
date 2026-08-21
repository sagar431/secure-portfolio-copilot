from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatRequestTrace, Conversation, Message


async def create_conversation(
    session: AsyncSession, *, tenant_id: UUID, user_id: UUID, title: str
) -> Conversation:
    conversation = Conversation(tenant_id=tenant_id, user_id=user_id, title=title)
    session.add(conversation)
    await session.flush()
    await session.refresh(conversation)
    return conversation


async def list_owned_conversations(
    session: AsyncSession, *, tenant_id: UUID, user_id: UUID
) -> tuple[Conversation, ...]:
    rows = (
        (
            await session.execute(
                select(Conversation)
                .where(
                    Conversation.tenant_id == tenant_id,
                    Conversation.user_id == user_id,
                )
                .order_by(Conversation.last_activity_at.desc(), Conversation.id)
            )
        )
        .scalars()
        .all()
    )
    return tuple(rows)


async def get_owned_conversation(
    session: AsyncSession, *, conversation_id: UUID, tenant_id: UUID, user_id: UUID
) -> Conversation | None:
    return (
        (
            await session.execute(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.tenant_id == tenant_id,
                    Conversation.user_id == user_id,
                )
            )
        )
        .scalars()
        .one_or_none()
    )


async def add_message(
    session: AsyncSession,
    *,
    conversation: Conversation,
    user_id: UUID,
    role: str,
    content: str,
    request_id: str,
) -> Message:
    now = datetime.now(UTC)
    message = Message(
        conversation_id=conversation.id,
        tenant_id=conversation.tenant_id,
        user_id=user_id,
        role=role,
        content=content,
        request_id=request_id,
    )
    conversation.last_activity_at = now
    conversation.updated_at = now
    session.add(message)
    await session.flush()
    return message


def add_trace(
    session: AsyncSession,
    *,
    request_id: str,
    conversation: Conversation,
    user_id: UUID,
    model_name: str,
    status: str,
    reason_code: str,
    document_ids: tuple[UUID, ...],
    chunk_ids: tuple[UUID, ...],
    input_tokens: int | None,
    output_tokens: int | None,
    latency_ms: int,
    retry_count: int,
    route_reason_code: str = "NO_MODEL_CALL",
    fallback_used: bool = False,
    fallback_reason_code: str | None = None,
) -> None:
    session.add(
        ChatRequestTrace(
            request_id=request_id,
            conversation_id=conversation.id,
            tenant_id=conversation.tenant_id,
            user_id=user_id,
            model_name=model_name,
            status=status,
            reason_code=reason_code,
            retrieved_document_ids=[str(item) for item in document_ids],
            retrieved_chunk_ids=[str(item) for item in chunk_ids],
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=max(0, latency_ms),
            retry_count=max(0, retry_count),
            route_reason_code=route_reason_code,
            fallback_used=fallback_used,
            fallback_reason_code=fallback_reason_code,
        )
    )
