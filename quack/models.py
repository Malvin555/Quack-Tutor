"""Pydantic schemas used across Quack. No logic."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Symbol(BaseModel):
    """A function/class/variable found by the regex extractor."""

    file: str
    name: str
    kind: Literal["function", "class", "variable"]
    start_line: int
    end_line: int
    signature: str


class FileRecord(BaseModel):
    """A row of the files table, optionally with a retrieval score."""

    path: str
    language: str
    line_count: int
    hash: str
    score: float = 0.0


class Task(BaseModel):
    """One thing the engineer should do. Quack never does it for them."""

    file: str
    line: int
    severity: Literal["critical", "suggestion"]
    description: str
    why: str


class TutorResponse(BaseModel):
    """Structured answer returned by the model."""

    socratic_question: str
    explanation: str
    tasks: list[Task]
    concept_tags: list[str]
    confidence: Literal["high", "medium", "low"]
    related_files: list[str] = Field(default_factory=list)


class IndexStats(BaseModel):
    """Summary printed after indexing."""

    files: int
    symbols: int
    mentions: int
    todos: int
    duration_ms: int
