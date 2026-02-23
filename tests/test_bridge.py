"""Tests for proxi.bridge.StdioEmitter."""

import io
import json
import sys

import pytest

from proxi.bridge import StdioEmitter


def test_emit_writes_json_line() -> None:
    """emit writes JSON-serialized message + newline to stdout."""
    buf = io.StringIO()
    with pytest.MonkeyPatch.context() as m:
        m.setattr(sys, "stdout", buf)
        emitter = StdioEmitter()
        emitter.emit({"type": "ready"})
    line = buf.getvalue()
    assert line.endswith("\n")
    obj = json.loads(line.strip())
    assert obj == {"type": "ready"}


def test_emit_after_close_does_nothing() -> None:
    """emit is no-op after _closed is True."""
    buf = io.StringIO()
    with pytest.MonkeyPatch.context() as m:
        m.setattr(sys, "stdout", buf)
        emitter = StdioEmitter()
        emitter._closed = True
        emitter.emit({"type": "ready"})
    assert buf.getvalue() == ""
