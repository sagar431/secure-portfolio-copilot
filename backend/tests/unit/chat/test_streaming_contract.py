import asyncio
import json
from typing import Any, cast
from uuid import uuid4

import pytest
from starlette.requests import Request

from app.api.routes.conversations import stream_message
from app.chat.intent import RequestIntent
from app.chat.streaming import RouteSelected
from app.schemas.chat import CreateMessageRequest


class _Session:
    def __init__(self) -> None:
        self.rollback_calls = 0

    async def rollback(self) -> None:
        self.rollback_calls += 1


class _BlockingService:
    def __init__(self) -> None:
        self.session = _Session()
        self.cancelled = asyncio.Event()

    async def answer(self, *args: object, **kwargs: Any) -> object:
        del args
        kwargs["progress"](RouteSelected(intent=RequestIntent.DOCUMENT_QUESTION))
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


def _request() -> Request:
    request = Request({"type": "http", "method": "POST", "path": "/"})
    request.state.request_id = "stream-cancellation-test"
    return request


@pytest.mark.asyncio
async def test_closing_stream_cancels_answer_task_and_rolls_back() -> None:
    service = _BlockingService()
    response = await stream_message(
        uuid4(),
        CreateMessageRequest(content="What was revenue?"),
        _request(),
        cast(Any, object()),
        cast(Any, service),
    )
    iterator = cast(Any, response.body_iterator)
    started = json.loads((await anext(iterator)).decode())
    route = json.loads((await anext(iterator)).decode())
    assert started == {"type": "message.started"}
    assert route == {"type": "route.selected", "intent": "DOCUMENT_QUESTION"}

    await iterator.aclose()

    await asyncio.wait_for(service.cancelled.wait(), timeout=1)
    assert service.session.rollback_calls == 1
