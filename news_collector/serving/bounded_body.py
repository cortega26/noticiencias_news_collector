"""Admission control for routes that accept bounded JSON or multipart bodies."""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import HTTPException, Request, Response
from fastapi.routing import APIRoute
from starlette.requests import ClientDisconnect
from starlette.types import Message

VerifyAuthorization = Callable[[str | None], None]
BodyLimitError = Callable[[int, int], HTTPException]


def bounded_body_route(
    verify: VerifyAuthorization,
    get_limit: Callable[[], int],
    over_limit: BodyLimitError,
    *,
    declared_first: bool = False,
) -> type[APIRoute]:
    """Attach admission to the actual route, before FastAPI invokes a parser."""

    class BoundedBodyRoute(APIRoute):
        def get_route_handler(
            self,
        ) -> Callable[[Request], Coroutine[Any, Any, Response]]:
            handler = super().get_route_handler()

            async def guarded(request: Request) -> Response:
                limit = get_limit()
                declared = request.headers.get("content-length", "").lstrip("0")
                if not declared_first:
                    verify(request.headers.get("authorization"))
                if _declared_too_large(declared, limit):
                    # The exception may report the limit, so avoid decoding
                    # arbitrarily long Content-Length values as Python ints.
                    size = int(declared) if len(declared) <= 20 else limit + 1
                    raise over_limit(size, limit)
                if declared_first:
                    verify(request.headers.get("authorization"))

                admitted: bytes | None = await _read_admitted_body(
                    request, limit, over_limit
                )

                async def admitted_body() -> Message:
                    nonlocal admitted
                    if admitted is None:
                        return await request.receive()
                    content, admitted = admitted, None
                    return {"type": "http.request", "body": content, "more_body": False}

                return await handler(Request(request.scope, receive=admitted_body))

            return guarded

    return BoundedBodyRoute


async def _read_admitted_body(
    request: Request, limit: int, over_limit: BodyLimitError
) -> bytes:
    # Finish admission before creating multipart parser state or temporary files.
    body = bytearray()
    try:
        async for chunk in request.stream():
            size = len(body) + len(chunk)
            if size > limit:
                raise over_limit(size, limit)
            body.extend(chunk)
    except ClientDisconnect as exc:
        raise HTTPException(400, "There was an error parsing the body") from exc
    return bytes(body)


def _declared_too_large(declared: str, limit: int) -> bool:
    if not declared or not declared.isascii() or not declared.isdecimal():
        return False
    maximum = str(limit)
    return (len(declared), declared) > (len(maximum), maximum)
