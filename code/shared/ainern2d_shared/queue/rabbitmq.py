from __future__ import annotations

import json
from typing import Callable

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
		self._channel.queue_declare(queue=topic, durable=True)
		body = message if isinstance(message, str) else json.dumps(message, ensure_ascii=False)
		self._channel.basic_publish(
			exchange="",
			routing_key=topic,
			body=body.encode("utf-8"),
			properties=pika.BasicProperties(delivery_mode=2),
		)

	def close(self):
		if self._connection and not self._connection.is_closed:
			self._connection.close()


class RabbitMQConsumer:
	def __init__(self, amqp_url: str):
		if pika is None:
			raise RuntimeError("pika is required for RabbitMQConsumer")
		self._connection = pika.BlockingConnection(pika.URLParameters(amqp_url))
		self._channel = self._connection.channel()

	def consume(self, topic: str, handler: Callable[[dict], None], auto_ack: bool = False) -> None:
		self._channel.queue_declare(queue=topic, durable=True)

		def _on_message(ch, method, _properties, body):
			try:
				payload = json.loads(body.decode("utf-8"))
			except Exception:
				payload = {"raw": body.decode("utf-8", errors="replace")}

			handler(payload)
			if not auto_ack:
				ch.basic_ack(delivery_tag=method.delivery_tag)

		self._channel.basic_qos(prefetch_count=10)
		self._channel.basic_consume(queue=topic, on_message_callback=_on_message, auto_ack=auto_ack)
		self._channel.start_consuming()

	def close(self):
		if self._connection and not self._connection.is_closed:
			self._connection.close()

