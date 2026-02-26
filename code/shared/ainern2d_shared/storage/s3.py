from __future__ import annotations

try:
	import boto3
except Exception:
	boto3 = None


class S3Storage:
	def __init__(self, endpoint: str, access_key: str, secret_key: str):
		if boto3 is None:
			raise RuntimeError("boto3 is required for S3Storage")
		self._client = boto3.client(
			"s3",
			endpoint_url=endpoint,
			aws_access_key_id=access_key,
			aws_secret_access_key=secret_key,
		)

	def put_object(self, bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
		self._client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)

