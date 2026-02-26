from __future__ import annotations

import logging
import sys

try:
	from loguru import logger as _logger
except Exception:
	_logger = None


def get_logger(name: str = "ainer"):
	if _logger is not None:
		return _logger.bind(module=name)

	logger = logging.getLogger(name)
	if not logger.handlers:
		handler = logging.StreamHandler(sys.stdout)
		handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
		logger.addHandler(handler)
	logger.setLevel(logging.INFO)
	return logger

