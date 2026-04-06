import pytest
from src.governance.dlq import DLQHandler, NullDLQHandler, create_dlq_handler

def test_null_handler_accepts_all():
    handler = NullDLQHandler()
    assert handler.add_failed_node("node-1", {"error": "boom"}) is True
    assert handler.get_failed_nodes() == []
    assert handler.retry_node("node-1") is False

def test_dlq_handler_stores_failures():
    handler = DLQHandler()
    handler.add_failed_node("node-1", {"error": "timeout"})
    handler.add_failed_node("node-2", {"error": "crash"})
    failed = handler.get_failed_nodes()
    assert len(failed) == 2
    assert failed[0]["node_id"] == "node-1"

def test_dlq_handler_retry_removes():
    handler = DLQHandler()
    handler.add_failed_node("node-1", {"error": "timeout"})
    assert handler.retry_node("node-1") is True
    assert len(handler.get_failed_nodes()) == 0

def test_dlq_handler_max_retries():
    handler = DLQHandler(max_retries=2)
    handler.add_failed_node("node-1", {"error": "fail"})
    assert handler.retry_node("node-1") is True
    handler.add_failed_node("node-1", {"error": "fail again"})
    assert handler.retry_node("node-1") is True
    handler.add_failed_node("node-1", {"error": "fail third"})
    assert handler.retry_node("node-1") is False

def test_factory_enabled():
    handler = create_dlq_handler(enabled=True)
    assert isinstance(handler, DLQHandler)

def test_factory_disabled():
    handler = create_dlq_handler(enabled=False)
    assert isinstance(handler, NullDLQHandler)
