"""HTTP channel adapters for direct invocation and TUI SSE streaming."""

from __future__ import annotations

import asyncio
from typing import Any

from proxi.gateway.events import GatewayEvent, ReplyChannel


def _answers_from_ask_user_question_chat(form_req: Any, text: str) -> dict[str, Any]:
    """Map a free-form chat line to form answers when the user replies in the main input."""
    raw = text.strip()
    if not raw:
        raw = text
    if form_req is None or not getattr(form_req, "questions", None):
        return {"reply": raw}

    qs = list(form_req.questions)
    if len(qs) == 1:
        q = qs[0]
        qid = q.id
        if q.type == "text":
            return {qid: raw}
        if q.type == "choice":
            low = raw.lower()
            for o in q.options or []:
                if low == o.lower() or low in o.lower() or o.lower() in low:
                    return {qid: o}
            return {qid: raw}
        if q.type == "multiselect":
            low = raw.lower()
            picks = [o for o in (q.options or []) if low in o.lower() or o.lower() in low]
            if picks:
                return {qid: picks}
            return {qid: [raw]}
        if q.type == "yesno":
            return {qid: raw.lower() in ("y", "yes", "true", "1")}

    for q in qs:
        if q.type == "text":
            return {q.id: raw}
    for q in qs:
        if q.type == "choice":
            low = raw.lower()
            for o in q.options or []:
                if low == o.lower() or low in o.lower() or o.lower() in low:
                    return {q.id: o}
    return {qs[0].id: raw}


class HttpReplyChannel(ReplyChannel):
    """Collects agent output into an asyncio queue for synchronous HTTP responses."""

    source_type: str = "http"  # type: ignore[assignment]
    _queue: asyncio.Queue[str] = None  # type: ignore[assignment]

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._queue = asyncio.Queue()

    async def send(self, text: str) -> None:
        await self._queue.put(text)

    async def collect(self, timeout: float = 300.0) -> str:
        """Wait for the first reply (or timeout)."""
        return await asyncio.wait_for(self._queue.get(), timeout=timeout)

    model_config = {"arbitrary_types_allowed": True}


class HttpNoopReplyChannel(ReplyChannel):
    """No-op reply channel used when no SSE listener is attached."""

    source_type: str = "http"  # type: ignore[assignment]

    async def send(self, text: str) -> None:
        return


class HttpSseReplyChannel(ReplyChannel):
    """Reply channel backed by an ``asyncio.Queue`` for SSE consumers."""

    source_type: str = "http"  # type: ignore[assignment]
    _queue: asyncio.Queue[dict[str, Any] | None] = None  # type: ignore[assignment]

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._queue = asyncio.Queue()

    async def send(self, text: str) -> None:
        await self.send_event({"type": "text_stream", "content": text})

    async def send_event(self, event: dict[str, Any]) -> None:
        await self._queue.put(event)

    async def stream(self):
        """Async generator consumed by the SSE endpoint."""
        while True:
            item = await self._queue.get()
            if item is None:
                break
            yield item

    async def close(self) -> None:
        await self._queue.put(None)

    model_config = {"arbitrary_types_allowed": True}


class HttpFormBridge:
    """Form bridge for HTTP/SSE transport."""

    def __init__(self, channel: HttpSseReplyChannel) -> None:
        self._channel = channel
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._pending_forms: dict[str, Any] = {}

    async def request_form(self, tool_call_id: str, form_request: Any) -> dict[str, Any]:
        payload = {
            "type": "user_input_required",
            "payload": {
                "tool_call_id": tool_call_id,
                "goal": form_request.goal,
                "title": form_request.title,
                "questions": [q.model_dump(exclude_none=True) for q in form_request.questions],
                "allow_skip": form_request.allow_skip,
            },
        }
        await self._channel.send_event(payload)
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[tool_call_id] = fut
        self._pending_forms[tool_call_id] = form_request
        try:
            return await fut
        finally:
            self._pending.pop(tool_call_id, None)
            self._pending_forms.pop(tool_call_id, None)

    def consume_chat_as_form_reply(self, text: str) -> bool:
        """If exactly one form is awaiting input, treat ``text`` as the user's answers.

        Unblocks `request_form` without a separate /send form_answer payload — used when
        the TUI chat line is used instead of the AnswerForm overlay (parse failure, UX).
        """
        if len(self._pending) != 1:
            return False
        tool_call_id = next(iter(self._pending))
        fut = self._pending.get(tool_call_id)
        if fut is None or fut.done():
            return False
        form_req = self._pending_forms.get(tool_call_id)
        answers = _answers_from_ask_user_question_chat(form_req, text)
        fut.set_result(
            {
                "tool_call_id": tool_call_id,
                "answers": answers,
                "skipped": False,
            }
        )
        return True

    async def inject_answer(self, form_answer: dict[str, Any]) -> None:
        tool_call_id = str(form_answer.get("tool_call_id", ""))
        if not tool_call_id:
            return
        fut = self._pending.get(tool_call_id)
        if fut is None or fut.done():
            return
        fut.set_result(form_answer)


def build_http_event(
    message: str,
    session_id: str = "",
) -> tuple[GatewayEvent, HttpReplyChannel]:
    """Build a ``GatewayEvent`` + ``HttpReplyChannel`` for direct invocation."""
    reply = HttpReplyChannel(destination="http-caller")
    event = GatewayEvent(
        source_id="http",
        source_type="http",
        payload={"text": message},
        reply_channel=reply,
        session_id=session_id,
    )
    return event, reply
