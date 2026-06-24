"""Request-scoped context variables propagated from middleware to service layer."""
from __future__ import annotations
from contextvars import ContextVar
import uuid

_request_id: ContextVar[str] = ContextVar("request_id", default="")
_ip_address: ContextVar[str] = ContextVar("ip_address", default="")
_user_agent: ContextVar[str] = ContextVar("user_agent", default="")


def set_request_context(request_id: str, ip_address: str, user_agent: str) -> None:
    _request_id.set(request_id)
    _ip_address.set(ip_address)
    _user_agent.set(user_agent)


def get_request_id() -> str:
    return _request_id.get() or ""


def get_ip_address() -> str:
    return _ip_address.get() or ""


def get_user_agent() -> str:
    return _user_agent.get() or ""


def new_request_id() -> str:
    return uuid.uuid4().hex
