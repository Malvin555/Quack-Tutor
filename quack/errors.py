"""Exception types shared across Quack."""

from __future__ import annotations


class QuackError(Exception):
    """Base class for all expected Quack errors."""


class TutorError(QuackError):
    """The LLM call failed (timeout, bad JSON, provider error)."""


class ProviderError(TutorError):
    """A provider could not be reached, authenticated, or is not allowed."""
