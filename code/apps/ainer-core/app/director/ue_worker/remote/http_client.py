"""UE Remote Control API（HTTP，默认 30010 端口）。

用到的端点：
  GET  /remote/info                      探活
  PUT  /remote/object/call               调 UObject 函数（{objectPath, functionName, parameters, generateTransaction}）
  PUT  /remote/object/property           读写属性（{objectPath, propertyName, access, propertyValue}）
  PUT  /remote/batch                     一次发多条（{Requests: [{RequestId, URL, Verb, Body}]}）
执行 Unreal Python：调 PythonScriptLibrary.ExecutePythonCommand（UE 里要开 Python 插件，并在
Remote Control 设置里允许远程执行 Python）。
"""
from __future__ import annotations

from typing import Any

import httpx

PYTHON_LIB = "/Script/PythonScriptPlugin.Default__PythonScriptLibrary"


class UERemoteError(RuntimeError):
    pass


class UERemoteHTTP:
    def __init__(self, base_url: str = "http://127.0.0.1:30010", *, timeout: float = 30, transport: httpx.BaseTransport | None = None):
        self.base = base_url.rstrip("/")
        self.client = httpx.Client(base_url=self.base, timeout=timeout, transport=transport)

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "UERemoteHTTP":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _put(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        r = self.client.put(path, json=body)
        if r.status_code >= 400:
            raise UERemoteError(f"UE {path} {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else {}

    def info(self) -> dict[str, Any]:
        r = self.client.get("/remote/info")
        if r.status_code >= 400:
            raise UERemoteError(f"UE 不在线：{r.status_code}")
        return r.json()

    @staticmethod
    def call_body(object_path: str, function: str, parameters: dict[str, Any] | None = None, transaction: bool = True) -> dict[str, Any]:
        return {"objectPath": object_path, "functionName": function, "parameters": parameters or {}, "generateTransaction": transaction}

    def call(self, object_path: str, function: str, parameters: dict[str, Any] | None = None, transaction: bool = True) -> dict[str, Any]:
        return self._put("/remote/object/call", self.call_body(object_path, function, parameters, transaction))

    def set_property(self, object_path: str, name: str, value: Any) -> dict[str, Any]:
        return self._put("/remote/object/property", {"objectPath": object_path, "propertyName": name,
                                                     "access": "WRITE_TRANSACTION_ACCESS", "propertyValue": {name: value}})

    def batch(self, calls: list[dict[str, Any]]) -> dict[str, Any]:
        reqs = [{"RequestId": i + 1, "URL": "/remote/object/call", "Verb": "PUT", "Body": c} for i, c in enumerate(calls)]
        return self._put("/remote/batch", {"Requests": reqs})

    def run_python(self, source: str) -> dict[str, Any]:
        return self.call(PYTHON_LIB, "ExecutePythonCommand", {"PythonCommand": source}, transaction=False)
