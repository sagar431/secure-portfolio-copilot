from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessageRequest, ChatRequestTrace, Conversation, Message


async def get_chat_message_request(
    session: AsyncSession,
    *,
    conversation_id: UUID,
    tenant_id: UUID,
    user_id: UUID,
    client_message_id: UUID,
) -> ChatMessageRequest | None:
    return (
        (
            await session.execute(
                select(ChatMessageRequest).where(
                    ChatMessageRequest.conversation_id == conversation_id,
                    ChatMessageRequest.tenant_id == tenant_id,
                    ChatMessageRequest.user_id == user_id,
                    ChatMessageRequest.client_message_id == client_message_id,
                )
            )
        )
        .scalars()
        .one_or_none()
    )


async def create_chat_message_request(
    session: AsyncSession,
    *,
    conversation_id: UUID,
    tenant_id: UUID,
    user_id: UUID,
    client_message_id: UUID,
    request_fingerprint: str,
) -> ChatMessageRequest:
    record = ChatMessageRequest(
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        user_id=user_id,
        client_message_id=client_message_id,
        request_fingerprint=request_fingerprint,
        status="PENDING",
    )
    session.add(record)
    await session.flush()
    return record


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
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    return tuple(rows)


async def bounded_user_messages_for_conversations(
    session: AsyncSession,
    *,
    conversation_ids: tuple[UUID, ...],
    tenant_id: UUID,
    user_id: UUID,
) -> dict[UUID, tuple[str, ...]]:
    """Load up to five title candidates per owned legacy conversation in one query."""
    if not conversation_ids:
        return {}
    ranked = (
        select(
            Message.conversation_id,
            Message.content,
            func.row_number()
            .over(
                partition_by=Message.conversation_id,
                order_by=(Message.created_at, Message.id),
            )
            .label("message_rank"),
        )
        .where(
            Message.conversation_id.in_(conversation_ids),
            Message.tenant_id == tenant_id,
            Message.user_id == user_id,
            Message.role == "user",
        )
        .subquery()
    )
    rows = (
        await session.execute(
            select(ranked.c.conversation_id, ranked.c.content)
            .where(ranked.c.message_rank <= 5)
            .order_by(ranked.c.conversation_id, ranked.c.message_rank)
        )
    ).all()
    result: dict[UUID, list[str]] = {}
    for conversation_id, content in rows:
        result.setdefault(conversation_id, []).append(content)
    return {key: tuple(values) for key, values in result.items()}


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
        created_at=now,
    )
    conversation.last_activity_at = now
    conversation.updated_at = now
    session.add(message)
    await session.flush()
    return message


async def load_bounded_conversation_messages(
    session: AsyncSession,
    *,
    conversation_id: UUID,
    tenant_id: UUID,
    user_id: UUID,
    limit: int,
) -> tuple[Message, ...]:
    """Load only the authenticated owner's newest conversation messages, in prompt order."""
    role_order = case((Message.role == "user", 0), else_=1)
    newest = (
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.tenant_id == tenant_id,
            Message.user_id == user_id,
        )
        .order_by(Message.created_at.desc(), role_order.desc(), Message.id.desc())
        .limit(limit)
        .subquery()
    )
    rows = (
        (
            await session.execute(
                select(Message)
                .join(newest, Message.id == newest.c.id)
                .order_by(Message.created_at, role_order, Message.id)
            )
        )
        .scalars()
        .all()
    )
    return tuple(rows)


async def count_owned_conversation_messages(
    session: AsyncSession, *, conversation_id: UUID, tenant_id: UUID, user_id: UUID
) -> int:
    return int(
        await session.scalar(
            select(func.count(Message.id)).where(
                Message.conversation_id == conversation_id,
                Message.tenant_id == tenant_id,
                Message.user_id == user_id,
            )
        )
        or 0
    )


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
    intent_route: str = "DOCUMENT_QUESTION",
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
            intent_route=intent_route,
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
