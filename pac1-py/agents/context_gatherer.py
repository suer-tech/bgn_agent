"""Context Gatherer — deterministic pre-execution context collection.

Searches the repo for all records related to target entities,
reads them, and extracts ALL date mentions with surrounding context.
Each date mention includes: file path, label/context text, date value.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from bitgn.vm.pcm_connect import PcmRuntimeClientSync
from agents.pcm_helpers import safe_search, safe_read_file


# ── Date extraction patterns ──

# ISO dates: 2026-04-14
ISO_DATE = re.compile(r'\b(\d{4}-\d{2}-\d{2})\b')
ISO_DATE_STRICT = re.compile(r'^\d{4}-\d{2}-\d{2}$')

# Prose dates: "March 15, 2026", "15 March 2026", "Mar 15 2026"
MONTH_NAMES = r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
PROSE_DATE_MDY = re.compile(rf'\b({MONTH_NAMES})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s*(\d{{4}})\b', re.IGNORECASE)
PROSE_DATE_DMY = re.compile(rf'\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({MONTH_NAMES}),?\s*(\d{{4}})\b', re.IGNORECASE)

MONTH_MAP = {
    'jan': 1, 'january': 1, 'feb': 2, 'february': 2, 'mar': 3, 'march': 3,
    'apr': 4, 'april': 4, 'may': 5, 'jun': 6, 'june': 6,
    'jul': 7, 'july': 7, 'aug': 8, 'august': 8, 'sep': 9, 'september': 9,
    'oct': 10, 'october': 10, 'nov': 11, 'november': 11, 'dec': 12, 'december': 12,
}


@dataclass
class DateMention:
    """A single date found in a file, with context."""
    file_path: str
    label: str       # preceding text / field name that describes what this date is
    value: str       # ISO date string YYYY-MM-DD
    raw_text: str    # original text as found in file


@dataclass
class EntityContext:
    """All gathered context for a single entity."""
    entity_name: str
    related_files: Dict[str, str] = field(default_factory=dict)
    date_mentions: List[DateMention] = field(default_factory=list)

    def format_date_table(self) -> str:
        """Format all date mentions as a structured table for LLM."""
        if not self.date_mentions:
            return ""
        lines = [f"### ALL DATES found for: {self.entity_name}"]
        lines.append("| File | Context/Label | Date |")
        lines.append("|------|---------------|------|")
        for dm in sorted(self.date_mentions, key=lambda d: d.value):
            label = dm.label.replace("|", "/").strip()
            lines.append(f"| {dm.file_path} | {label} | {dm.value} |")
        return "\n".join(lines)


def gather_entity_context(
    vm: PcmRuntimeClientSync,
    target_entities: List[str],
) -> Dict[str, EntityContext]:
    """Search repo for all mentions of target entities, read files, extract dates with context."""
    results: Dict[str, EntityContext] = {}
    seen_files: set = set()

    for entity in target_entities:
        ctx = EntityContext(entity_name=entity)

        search_term = _extract_search_term(entity)
        if not search_term:
            continue

        # Search across entire repo
        matches = safe_search(vm, search_term, root="/", limit=20)
        file_paths = set()
        for match in matches:
            path = match.get("path", "")
            if path and not _is_infrastructure_file(path):
                file_paths.add(path)

        # Also search within notes directory specifically
        notes_matches = safe_search(vm, search_term, root="/01_notes", limit=10)
        for match in notes_matches:
            path = match.get("path", "")
            if path and not _is_infrastructure_file(path):
                file_paths.add(path)

        # Read each file and extract dates with context
        # Also collect cross-references to follow
        cross_ref_paths = set()

        for path in file_paths:
            if path in seen_files:
                continue
            seen_files.add(path)

            content = safe_read_file(vm, path)
            if content is None:
                continue

            ctx.related_files[path] = content

            # Extract all date mentions with context
            if path.endswith(".json"):
                mentions = _extract_dates_from_json(path, content)
                # Follow cross-references: contact IDs, account IDs
                cross_ref_paths.update(_extract_cross_refs(content))
            else:
                mentions = _extract_dates_from_text(path, content)

            ctx.date_mentions.extend(mentions)

        # Read cross-referenced files (contacts, linked records)
        for ref_path in cross_ref_paths:
            if ref_path in seen_files:
                continue
            seen_files.add(ref_path)

            content = safe_read_file(vm, ref_path)
            if content is None:
                continue

            ctx.related_files[ref_path] = content
            if ref_path.endswith(".json"):
                mentions = _extract_dates_from_json(ref_path, content)
                ctx.date_mentions.extend(mentions)

        if ctx.related_files:
            results[entity] = ctx

    return results


def format_gathered_context(contexts: Dict[str, EntityContext]) -> str:
    """Format all gathered contexts into a prompt section with date tables."""
    if not contexts:
        return ""

    sections = []
    for ctx in contexts.values():
        table = ctx.format_date_table()
        if table:
            sections.append(table)

    if not sections:
        return ""

    return "## PRE-GATHERED ENTITY CONTEXT (read by system before your first step)\n\n" + "\n\n".join(sections)


# ── Date extraction from JSON ──

def _extract_dates_from_json(file_path: str, content: str) -> List[DateMention]:
    """Extract all date fields from JSON with their field names as labels."""
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return []

    mentions = []
    _walk_json(data, "", file_path, mentions)
    return mentions


def _walk_json(obj: Any, prefix: str, file_path: str, mentions: List[DateMention]):
    """Recursively walk JSON and find date-valued fields."""
    if isinstance(obj, dict):
        for key, val in obj.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(val, str) and ISO_DATE_STRICT.match(val):
                mentions.append(DateMention(
                    file_path=file_path,
                    label=full_key,
                    value=val,
                    raw_text=f'"{key}": "{val}"',
                ))
            elif isinstance(val, (dict, list)):
                _walk_json(val, full_key, file_path, mentions)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _walk_json(item, f"{prefix}[{i}]", file_path, mentions)


# ── Date extraction from text/markdown ──

def _extract_dates_from_text(file_path: str, content: str) -> List[DateMention]:
    """Extract all dates from text with preceding context as labels."""
    mentions = []
    seen_values = set()

    # 1. ISO dates with preceding context
    for m in ISO_DATE.finditer(content):
        date_val = m.group(1)
        label = _get_preceding_context(content, m.start(), max_chars=80)
        mentions.append(DateMention(
            file_path=file_path, label=label, value=date_val, raw_text=m.group(0),
        ))
        seen_values.add(date_val)

    # 2. Prose dates: "March 15, 2026" format
    for m in PROSE_DATE_MDY.finditer(content):
        month_str, day_str, year_str = m.group(1), m.group(2), m.group(3)
        iso = _prose_to_iso(month_str, day_str, year_str)
        if iso and iso not in seen_values:
            label = _get_preceding_context(content, m.start(), max_chars=80)
            mentions.append(DateMention(
                file_path=file_path, label=label, value=iso, raw_text=m.group(0),
            ))
            seen_values.add(iso)

    # 3. Prose dates: "15 March 2026" format
    for m in PROSE_DATE_DMY.finditer(content):
        day_str, month_str, year_str = m.group(1), m.group(2), m.group(3)
        iso = _prose_to_iso(month_str, day_str, year_str)
        if iso and iso not in seen_values:
            label = _get_preceding_context(content, m.start(), max_chars=80)
            mentions.append(DateMention(
                file_path=file_path, label=label, value=iso, raw_text=m.group(0),
            ))
            seen_values.add(iso)

    return mentions


def _prose_to_iso(month_str: str, day_str: str, year_str: str) -> Optional[str]:
    """Convert prose date parts to ISO format."""
    month_num = MONTH_MAP.get(month_str.lower())
    if not month_num:
        return None
    try:
        day = int(day_str)
        year = int(year_str)
        return f"{year:04d}-{month_num:02d}-{day:02d}"
    except ValueError:
        return None


def _get_preceding_context(text: str, pos: int, max_chars: int = 80) -> str:
    """Get the text preceding a match position, trimmed to the last newline or sentence start."""
    start = max(0, pos - max_chars)
    chunk = text[start:pos].strip()

    # Trim to last newline for cleaner context
    last_nl = chunk.rfind('\n')
    if last_nl >= 0:
        chunk = chunk[last_nl + 1:].strip()

    # Trim leading punctuation/whitespace
    chunk = chunk.lstrip('- *#>|')
    return chunk.strip() if chunk.strip() else "(start of file)"


# ── Helpers ──

def _extract_search_term(entity: str) -> str:
    """Extract a good search term from an entity reference."""
    if "/" in entity and ("inbox" in entity.lower() or "capture" in entity.lower() or "distill" in entity.lower()):
        return ""
    if "/" in entity:
        entity = entity.split("/")[-1]
    entity = re.sub(r'\.\w+$', '', entity)
    return entity.strip()


def _extract_cross_refs(content: str) -> List[str]:
    """Extract file paths for cross-referenced records from JSON content.

    Follows ID references like primary_contact_id, contact_id, account_id
    to their corresponding files in the known folder structure.
    """
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return []

    paths = []
    ref_map = {
        "primary_contact_id": "contacts/{}.json",
        "contact_id": "contacts/{}.json",
        "account_id": "accounts/{}.json",
        "account_manager_id": "contacts/{}.json",
    }

    if isinstance(data, dict):
        for field_name, path_template in ref_map.items():
            val = data.get(field_name)
            if val and isinstance(val, str):
                paths.append(path_template.format(val))

    return paths


def _is_infrastructure_file(path: str) -> bool:
    """Check if a file is infrastructure (README, AGENTS, templates)."""
    basename = path.split("/")[-1]
    return (
        basename.startswith("_")
        or basename.upper() in ("README.MD", "README.md", "AGENTS.MD", "AGENTS.md")
        or basename == "seq.json"
    )
