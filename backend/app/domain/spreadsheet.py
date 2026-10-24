"""Header matching shared by the Excel importers (leads and projects)."""

import re


def normalize_header(value) -> str:
    """Lowercase alphanumerics only, so 'Mobile No.' and 'mobile_no' compare equal."""
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def map_headers(header_row, aliases: dict) -> dict:
    """Map column index -> field name using the given alias table. The first
    column matching a field wins; later columns for the same field are ignored."""
    mapping = {}
    for idx, cell in enumerate(header_row):
        normalized = normalize_header(cell)
        for field, field_aliases in aliases.items():
            if normalized in field_aliases and field not in mapping.values():
                mapping[idx] = field
    return mapping
