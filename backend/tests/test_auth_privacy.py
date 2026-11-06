"""El scope del servidor no conserva code/state, incluso si falla una dependencia del callback."""

import asyncio

import pytest
from starlette.types import Message, Receive, Scope, Send


@pytest.mark.parametrize("root_path", ["", "/prefix"])
@pytest.mark.parametrize("fail", [False, True])
@pytest.mark.parametrize("path", ["/api/auth/callback", "/api/auth/callback/", "/api/studies"])
def test_callback_query_hidden_from_server_scope(path: str, fail: bool, root_path: str) -> None:
    from cerberus_api.routers.auth import CallbackPrivacyMiddleware

    async def receive() -> Message:
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        pass

    async def application(scope: Scope, receive: Receive, send: Send) -> None:
        assert scope["query_string"] == b"code=synthetic-secret&state=synthetic-state"
        if fail:
            raise RuntimeError("Dependencia no disponible")

    scope: Scope = {
        "type": "http",
        "path": root_path + path,
        "root_path": root_path,
        "query_string": b"code=synthetic-secret&state=synthetic-state",
    }
    operation = CallbackPrivacyMiddleware(application)(scope, receive, send)
    if fail:
        with pytest.raises(RuntimeError):
            asyncio.run(operation)
    else:
        asyncio.run(operation)
    expected = b"" if path.rstrip("/") == "/api/auth/callback" else b"code=synthetic-secret&state=synthetic-state"
    assert scope["query_string"] == expected
