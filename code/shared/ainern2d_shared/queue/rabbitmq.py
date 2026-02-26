from __future__ import annotations

import json

try:
	import pika
except Exception:
	pika = None


class RabbitMQPublisher:
	def __init__(self, amqp_url: str):
		if pika is None:
			raise RuntimeError("pika is required for RabbitMQPublisher")
		self._connection = pika.BlockingConnection(pika.URLParameters(amqp_url))
		self._channel = self._connection.channel()

	def publish(self, topic: str, message: str | dict):
		body = message if isinstance(message, str) else json.dumps(message, ensure_ascii=False)
		self._channel.basic_publish(exchange="", routing_key=topic, body=body.encode("utf-8"))

	def close(self):
		self._connection.close()

