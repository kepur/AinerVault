"""UE Remote Control API（WebSocket，默认 30020 端口）：长连接、推送事件时用。

消息格式：{"MessageName": "http", "Id": n, "Parameters": {"Url": "/remote/object/call", "Verb": "PUT", "Body": {...}}}
回包带同一个 Id。V1 不启用；这里只做封包/解包与收发，连接工厂可替换（测试用假连接）。
"""
from __future__ import annotations

import itertools
import json
from typing import Any, Callable

from app.director.ue_worker.remote.http_client import UERemoteError, UERemoteHTTP


def envelope(msg_id: int, url: str, body: dict[str, Any], verb: str = "PUT") -> dict[str, Any]:
    return {"MessageName": "http", "Id": msg_id, "Parameters": {"Url": url, "Verb": verb, "Body": body}}


class UERemoteWS:
    def __init__(self, url: str = "ws://127.0.0.1:30020", *, timeout: float = 30, connect: Callable[..., Any] | None = None):
        self.url, self.timeout = url, timeout
        self._connect = connect
        self._ws = None
        self._ids = itertools.count(1)

    def open(self) -> "UERemoteWS":
        if self._connect is None:
            import websocket          # websocket-client
            self._ws = websocket.create_connection(self.url, timeout=self.timeout)
        else:
            self._ws = self._connect(self.url, timeout=self.timeout)
        return self

    def close(self) -> None:
        if self._ws is not None:
            self._ws.close()
            self._ws = None

    def __enter__(self) -> "UERemoteWS":
        return self.open()

    def __exit__(self, *exc: object) -> None:
        self.close()

    def request(self, url: str, body: dict[str, Any], verb: str = "PUT") -> dict[str, Any]:
        if self._ws is None:
            raise UERemoteError("WebSocket 没连上")
        mid = next(self._ids)
        self._ws.send(json.dumps(envelope(mid, url, body, verb)))
        while True:
            reply = json.loads(self._ws.recv())
            if reply.get("RequestId") == mid or reply.get("Id") == mid:
                code = reply.get("ResponseCode", 200)
                if code >= 400:
                    raise UERemoteError(f"UE {url} {code}: {str(reply.get('ResponseBody'))[:300]}")
                return reply.get("ResponseBody") or {}

    def call(self, object_path: str, function: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request("/remote/object/call", UERemoteHTTP.call_body(object_path, function, parameters))
