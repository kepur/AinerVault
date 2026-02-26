from __future__ import annotations

try:
	from minio import Minio
except Exception:
	Minio = None


class MinioStorage:
	def __init__(self, endpoint: str, access_key: str, secret_key: str, secure: bool = False):
		if Minio is None:
			raise RuntimeError("minio package is required for MinioStorage")
		self._client = Minio(endpoint.replace("http://", "").replace("https://", ""), access_key, secret_key, secure=secure)

	def put_object(self, bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
		from io import BytesIO

		stream = BytesIO(data)
		self._client.put_object(bucket, key, stream, length=len(data), content_type=content_type)

