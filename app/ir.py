"""Intermediate representation: the single source of truth between pipeline stages."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class Block(BaseModel):
    type: str = "paragraph"  # heading | paragraph | list_item | table | marginalia | figure | other
    text: str = ""
    confidence: float = 1.0
    rows: Optional[list[list[str]]] = None  # table cells, row-major

    def table_rows(self) -> list[list[str]]:
        """Structured rows, falling back to parsing '| a | b |' lines from the text."""
        if self.rows:
            return self.rows
        out = []
        for line in self.text.splitlines():
            if "|" in line and not set(line.strip()) <= set("|-: "):
                out.append([c.strip() for c in line.strip().strip("|").split("|")])
        return out


class Routing(BaseModel):
    tier: int
    score: float
    model: str
    reasons: list[str] = Field(default_factory=list)
    escalated_from: Optional[int] = None


class Page(BaseModel):
    number: int
    image_path: Optional[str] = None
    source: str = "ocr"  # ocr | text_layer
    language: Optional[str] = None
    confidence: float = 0.0
    signals: dict = Field(default_factory=dict)
    routing: Optional[Routing] = None
    blocks: list[Block] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    status: str = "pending"  # pending | done | failed
    error: Optional[str] = None
    flagged: bool = False  # needs human review (see pipeline.needs_review)
    uncertain: int = 0  # count of [illegible] / [word?] markers
    edited: bool = False
    original_blocks: Optional[list[Block]] = None  # kept when a user edits, for later threshold review

    @property
    def text(self) -> str:
        return "\n\n".join(block_text(b) for b in self.blocks)


class DocumentIR(BaseModel):
    doc_id: str
    filename: str
    pages: list[Page] = Field(default_factory=list)


def block_text(b: Block) -> str:
    if b.type == "table":
        return "\n".join("\t".join(r) for r in b.table_rows()) or b.text
    return b.text
