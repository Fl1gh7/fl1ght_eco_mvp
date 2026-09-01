"""Проверка секретов вебхуков VK и Telegram."""

from __future__ import annotations

import secrets
from typing import Optional

from fastapi import HTTPException, status


def verify_shared_secret(
    provided: Optional[str],
    expected: str,
    *,
    missing_detail: str,
    invalid_detail: str = "Invalid webhook secret",
) -> None:
    """Сравнивает секрет за постоянное время. Пустой expected — сервис не настроен."""
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=missing_detail,
        )
    incoming = provided or ""
    if not secrets.compare_digest(incoming, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=invalid_detail,
        )
