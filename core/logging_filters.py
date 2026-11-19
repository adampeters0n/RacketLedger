"""Logging filters for structured instance tags."""

from __future__ import annotations

import logging

from django.conf import settings


class InstanceContextFilter(logging.Filter):
    """Přidá instance=/hostname do každého log záznamu."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.instance = getattr(settings, "INSTANCE_NAME", "unknown")
        return True
