from __future__ import annotations

import time
from functools import wraps
from typing import Callable, TypeVar


FunctionType = TypeVar("FunctionType", bound=Callable)


def retry_with_backoff(
	attempts: int = 3,
	base_delay_seconds: float = 0.5,
	max_delay_seconds: float = 5.0,
):
	def decorator(function: FunctionType) -> FunctionType:
		@wraps(function)
		def wrapper(*args, **kwargs):
			last_error = None
			for index in range(attempts):
				try:
					return function(*args, **kwargs)
				except Exception as error:
					last_error = error
					if index == attempts - 1:
						raise
					delay = min(base_delay_seconds * (2**index), max_delay_seconds)
					time.sleep(delay)
			if last_error:
				raise last_error

		return wrapper

	return decorator

