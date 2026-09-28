#!/usr/bin/env python3
"""
Ingest pipeline for RAG system.

Parses a PDF handbook, chunks by heading hierarchy, generates embeddings
via OpenAI, and upserts into PostgreSQL with pgvector.
"""

import json
import os
import re
import sys
from pathlib import Path

import fitz  # pymupdf
import psycopg2
import psycopg2.extras
import tiktoken
from openai import OpenAI

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "1536"))
CHUNK_MAX_TOKENS = int(os.environ.get("CHUNK_MAX_TOKENS", "800"))

PDF_PATH = "/data/Sample handbook.pdf"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

BATCH_SIZE = 100  # chunks per embedding API call

# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------
_enc = tiktoken.encoding_for_model("gpt-3.5-turbo")


def count_tokens(text: str) -> int:
    return len(_enc.encode(text))


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------
def run_schema(conn):
    """Execute schema.sql to create tables/indexes (idempotent via IF NOT EXISTS)."""
    sql = SCHEMA_PATH.read_text()
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    print("[schema] Tables and indexes ensured.")


# ---------------------------------------------------------------------------
# PDF parsing helpers
# ---------------------------------------------------------------------------
HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$")  # markdown-style headings
SOURCE_PATH_RE = re.compile(r"^contents/handbook/.+$", re.IGNORECASE)


def _detect_heading_level(line: str, span_font_size: float | None = None,
                          is_bold: bool = False) -> int | None:
    """Return heading level (1-3) or None if not a heading."""
    # Markdown-style headings
    m = HEADING_RE.match(line.strip())
    if m:
        return len(m.group(1))

    # Font-size heuristics (from PDF spans)
    if span_font_size is not None:
        if span_font_size >= 24 and is_bold:
            return 1
        if span_font_size >= 18 and is_bold:
            return 2
        if span_font_size >= 14 and is_bold:
            return 3

    return None


def _clean_heading(text: str) -> str:
    """Strip markdown hashes and whitespace from heading text."""
    return HEADING_RE.sub(r"\2", text.strip()).strip()


class Section:
    """A heading-delimited section extracted from the PDF."""

    def __init__(self, level: int, title: str, page_start: int):
        self.level = level
        self.title = title
        self.page_start = page_start
        self.page_end = page_start
        self.lines: list[str] = []
        self.source_md_path: str | None = None
        self.links: list[dict] = []

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def parse_pdf(pdf_path: str) -> list[Section]:
    """Parse PDF into a flat list of Sections, each tagged with heading level."""
    doc = fitz.open(pdf_path)
    sections: list[Section] = []
    current: Section | None = None

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]

        for block in blocks:
            if block.get("type") != 0:  # skip images
                continue

            for line_info in block.get("lines", []):
                spans = line_info.get("spans", [])
                if not spans:
                    continue

                line_text = "".join(s["text"] for s in spans).strip()
                if not line_text:
                    continue

                # Determine font properties from the first span
                first_span = spans[0]
                font_size = first_span.get("size", 12)
                is_bold = "bold" in first_span.get("font", "").lower() or \
                          (first_span.get("flags", 0) & (1 << 4)) != 0

                level = _detect_heading_level(line_text, font_size, is_bold)

                if level is not None:
                    title = _clean_heading(line_text)
                    sec = Section(level=level, title=title, page_start=page_idx)
                    sections.append(sec)
                    current = sec
                else:
                    if current is None:
                        # Content before first heading — create an implicit section
                        current = Section(level=1, title="(preamble)", page_start=page_idx)
                        sections.append(current)

                    current.lines.append(line_text)
                    current.page_end = page_idx

                    # Detect source_md_path lines
                    if SOURCE_PATH_RE.match(line_text) and current.source_md_path is None:
                        current.source_md_path = line_text.strip()

        # Extract links from page annotations
        for link in page.get_links():
            uri = link.get("uri")
            if uri and current is not None:
                current.links.append({"href": uri, "text": uri})

    # Also extract inline URIs from text via regex
    url_re = re.compile(r"https?://[^\s)\]>\"']+")
    for sec in sections:
        found_urls = set(l["href"] for l in sec.links)
        for m in url_re.finditer(sec.text):
            url = m.group(0).rstrip(".,;:")
            if url not in found_urls:
                sec.links.append({"href": url, "text": url})
                found_urls.add(url)

    doc.close()
    print(f"[parse] Extracted {len(sections)} sections from PDF.")
    return sections


# ---------------------------------------------------------------------------
# Heading chain & source path propagation
# ---------------------------------------------------------------------------
def build_heading_chains(sections: list[Section]) -> list[list[str]]:
    """
    For each section, return the heading chain (ancestor titles from H1 down).
    Also propagate source_md_path downward from H1 sections.
    """
    chain_stack: list[str] = []  # indexed by level-1
    level_stack: list[int] = []
    chains: list[list[str]] = []
    current_source: str | None = None

    for sec in sections:
        # Pop stack back to parent level
        while level_stack and level_stack[-1] >= sec.level:
            level_stack.pop()
            chain_stack.pop()

        chain_stack.append(sec.title)
        level_stack.append(sec.level)
        chains.append(list(chain_stack))

        # Propagate source_md_path from H1
        if sec.level == 1 and sec.source_md_path:
            current_source = sec.source_md_path
        if sec.source_md_path is None and current_source is not None:
            sec.source_md_path = current_source

    return chains


# ---------------------------------------------------------------------------
# Chunking logic
# ---------------------------------------------------------------------------

# Patterns for detecting table / code-block boundaries
TABLE_LINE_RE = re.compile(r"^\|.*\|$")
CODE_FENCE_RE = re.compile(r"^```")


def _is_inside_block(lines: list[str], idx: int) -> bool:
    """Return True if line at idx is inside a table or fenced code block."""
    in_code = False
    in_table = False
    for i, line in enumerate(lines):
        if CODE_FENCE_RE.match(line.strip()):
            in_code = not in_code
        if TABLE_LINE_RE.match(line.strip()):
            in_table = True
        elif in_table and not TABLE_LINE_RE.match(line.strip()) and line.strip():
            in_table = False

        if i == idx:
            return in_code or in_table
    return False


def _split_at_paragraphs(text: str, max_tokens: int, prefix: str) -> list[str]:
    """
    Split text at paragraph breaks (double newlines) ensuring no chunk
    exceeds max_tokens. Never split mid-table or mid-code-block.
    """
    paragraphs = re.split(r"\n{2,}", text)
    chunks: list[str] = []
    current_parts: list[str] = []
    current_tokens = count_tokens(prefix)

    for para in paragraphs:
        para_tokens = count_tokens(para)
        if current_parts and (current_tokens + para_tokens) > max_tokens:
            chunks.append("\n\n".join(current_parts))
            current_parts = [para]
            current_tokens = count_tokens(prefix) + para_tokens
        else:
            current_parts.append(para)
            current_tokens += para_tokens

    if current_parts:
        chunks.append("\n\n".join(current_parts))

    return chunks


class Chunk:
    """Final chunk ready for embedding and insertion."""

    def __init__(self, text: str, source_md_path: str, section_path: str,
                 department: str, page_start: int, page_end: int,
                 links: list[dict]):
        self.text = text
        self.source_md_path = source_md_path
        self.section_path = section_path
        self.department = department
        self.page_start = page_start
        self.page_end = page_end
        self.links = links
        self.embedding: list[float] | None = None


def chunk_sections(sections: list[Section], chains: list[list[str]]) -> list[Chunk]:
    """
    Chunk sections following the hierarchy rules:
      - Group by H2 boundaries
      - If > max tokens, split at H3
      - If still > max tokens, split at paragraph breaks
      - Prepend heading chain as context prefix
    """

    def _make_chunk(text: str, chain: list[str], sec: Section, suffix: str = "") -> Chunk:
        section_path = " > ".join(chain)
        if suffix:
            section_path = f"{section_path} > {suffix}"
        source = sec.source_md_path or "unknown"
        parts = source.strip("/").split("/")
        department = parts[1] if len(parts) > 1 else "general"
        return Chunk(
            text=text,
            source_md_path=source,
            section_path=section_path,
            department=department,
            page_start=sec.page_start,
            page_end=sec.page_end,
            links=list(sec.links),
        )

    chunks: list[Chunk] = []

    # Group sections: collect consecutive sections under each H2
    # We iterate through sections and gather H3+ children under their H2 parent
    i = 0
    while i < len(sections):
        sec = sections[i]
        chain = chains[i]
        prefix = " > ".join(chain) + "\n\n"

        # If this section is H1 or H2, gather its text plus children until next H1/H2
        if sec.level <= 2:
            # Collect child sections (H3+) under this H2/H1
            group_texts = [sec.text] if sec.text.strip() else []
            group_page_start = sec.page_start
            group_page_end = sec.page_end
            group_links = list(sec.links)
            child_sections: list[tuple[Section, list[str]]] = []
            j = i + 1

            while j < len(sections) and sections[j].level > sec.level:
                child_sections.append((sections[j], chains[j]))
                group_page_end = max(group_page_end, sections[j].page_end)
                group_links.extend(sections[j].links)
                j += 1

            combined_text = "\n\n".join(
                group_texts + [s.text for s, _ in child_sections if s.text.strip()]
            )
            total_tokens = count_tokens(prefix + combined_text)

            if total_tokens <= CHUNK_MAX_TOKENS:
                # Fits in one chunk
                chunks.append(_make_chunk(
                    prefix + combined_text, chain, sec
                ))
                # Update page range
                chunks[-1].page_start = group_page_start
                chunks[-1].page_end = group_page_end
                chunks[-1].links = group_links
            else:
                # Try splitting at H3 boundaries
                # First emit the H2's own text if any
                if sec.text.strip():
                    sec_text = prefix + sec.text
                    if count_tokens(sec_text) <= CHUNK_MAX_TOKENS:
                        chunks.append(_make_chunk(sec_text, chain, sec))
                    else:
                        # Split H2 body at paragraph breaks
                        para_chunks = _split_at_paragraphs(sec.text, CHUNK_MAX_TOKENS, prefix)
                        for ci, pc in enumerate(para_chunks):
                            suffix = f"part {ci + 1}" if len(para_chunks) > 1 else ""
                            chunks.append(_make_chunk(prefix + pc, chain, sec, suffix))

                # Now handle each child (H3) section individually
                for child_sec, child_chain in child_sections:
                    child_prefix = " > ".join(child_chain) + "\n\n"
                    child_full = child_prefix + child_sec.text
                    if count_tokens(child_full) <= CHUNK_MAX_TOKENS:
                        chunks.append(_make_chunk(child_full, child_chain, child_sec))
                    else:
                        # Split at paragraph breaks
                        para_chunks = _split_at_paragraphs(
                            child_sec.text, CHUNK_MAX_TOKENS, child_prefix
                        )
                        for ci, pc in enumerate(para_chunks):
                            suffix = f"part {ci + 1}" if len(para_chunks) > 1 else ""
                            chunks.append(_make_chunk(
                                child_prefix + pc, child_chain, child_sec, suffix
                            ))

            i = j
        else:
            # Standalone H3+ section not under an H2 — treat individually
            full_text = prefix + sec.text
            if count_tokens(full_text) <= CHUNK_MAX_TOKENS:
                chunks.append(_make_chunk(full_text, chain, sec))
            else:
                para_chunks = _split_at_paragraphs(sec.text, CHUNK_MAX_TOKENS, prefix)
                for ci, pc in enumerate(para_chunks):
                    suffix = f"part {ci + 1}" if len(para_chunks) > 1 else ""
                    chunks.append(_make_chunk(prefix + pc, chain, sec, suffix))
            i += 1

    # Deduplicate section_path — append counter if needed
    seen: dict[str, int] = {}
    for c in chunks:
        key = (c.source_md_path, c.section_path)
        if key in seen:
            seen[key] += 1
            c.section_path = f"{c.section_path} ({seen[key]})"
        else:
            seen[key] = 0

    print(f"[chunk] Created {len(chunks)} chunks.")
    return chunks


# ---------------------------------------------------------------------------
# Embedding generation
# ---------------------------------------------------------------------------
def generate_embeddings(chunks: list[Chunk]):
    """Call OpenAI embeddings API in batches of BATCH_SIZE."""
    client = OpenAI(api_key=OPENAI_API_KEY)
    total = len(chunks)

    for start in range(0, total, BATCH_SIZE):
        batch = chunks[start : start + BATCH_SIZE]
        texts = [c.text for c in batch]

        print(f"[embed] Requesting embeddings for chunks {start + 1}-{start + len(batch)}/{total} ...")
        response = client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=texts,
            dimensions=EMBEDDING_DIM,
        )

        for item in response.data:
            batch[item.index].embedding = item.embedding

    print(f"[embed] Generated embeddings for all {total} chunks.")


# ---------------------------------------------------------------------------
# Database upsert
# ---------------------------------------------------------------------------
def upsert_chunks(conn, chunks: list[Chunk]):
    """Upsert chunks into the chunks table."""
    sql = """
        INSERT INTO chunks (text, embedding, source_md_path, section_path,
                            department, page_start, page_end, links)
        VALUES (%s, %s::vector, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (source_md_path, section_path) DO UPDATE SET
            text = EXCLUDED.text,
            embedding = EXCLUDED.embedding,
            department = EXCLUDED.department,
            page_start = EXCLUDED.page_start,
            page_end = EXCLUDED.page_end,
            links = EXCLUDED.links;
    """
    with conn.cursor() as cur:
        for i, c in enumerate(chunks):
            embedding_str = "[" + ",".join(str(v) for v in c.embedding) + "]"
            cur.execute(sql, (
                c.text,
                embedding_str,
                c.source_md_path,
                c.section_path,
                c.department,
                c.page_start,
                c.page_end,
                json.dumps(c.links),
            ))

            if (i + 1) % 50 == 0:
                print(f"[upsert] {i + 1}/{len(chunks)} rows upserted ...")

    conn.commit()
    print(f"[upsert] Completed: {len(chunks)} rows upserted.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    # Validate environment
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL environment variable is required.", file=sys.stderr)
        sys.exit(1)
    if not OPENAI_API_KEY:
        print("ERROR: OPENAI_API_KEY environment variable is required.", file=sys.stderr)
        sys.exit(1)
    if not Path(PDF_PATH).exists():
        print(f"ERROR: PDF not found at {PDF_PATH}", file=sys.stderr)
        sys.exit(1)

    print(f"[config] EMBEDDING_MODEL={EMBEDDING_MODEL}  EMBEDDING_DIM={EMBEDDING_DIM}  "
          f"CHUNK_MAX_TOKENS={CHUNK_MAX_TOKENS}")

    # Connect to database
    print("[db] Connecting to PostgreSQL ...")
    conn = psycopg2.connect(DATABASE_URL)
    print("[db] Connected.")

    # Run schema
    run_schema(conn)

    # Parse PDF
    print(f"[parse] Opening {PDF_PATH} ...")
    sections = parse_pdf(PDF_PATH)

    # Build heading chains & propagate source paths
    chains = build_heading_chains(sections)

    # Chunk
    chunks = chunk_sections(sections, chains)

    if not chunks:
        print("WARNING: No chunks produced. Exiting.", file=sys.stderr)
        conn.close()
        sys.exit(1)

    # Generate embeddings
    generate_embeddings(chunks)

    # Upsert
    upsert_chunks(conn, chunks)

    conn.close()
    print("[done] Ingestion complete.")
    sys.exit(0)


if __name__ == "__main__":
    main()
