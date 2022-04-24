"""NAM exceptions."""
from __future__ import annotations


class NamError(Exception):
    """Base class for NAM errors."""

    def __init__(self, status: str) -> None:
        """Initialize."""
        super().__init__(status)
        self.status = status


class ApiError(NamError):
    """Raised when request ended in error."""


class ConnError(NamError):
    """Raised when request ended in error."""


class AuthFailed(NamError):
    """Raised if auth fails."""


class CannotGetMac(NamError):
    """Raised when cannot get device MAC address."""


class InvalidSensorData(NamError):
    """Raised when sensor data is invalid."""
