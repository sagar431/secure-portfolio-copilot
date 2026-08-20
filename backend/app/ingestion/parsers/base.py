import re
import unicodedata


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFC", value).replace("\x00", "")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in value.split("\n")).strip()


def is_formula_like(value: str) -> bool:
    candidate = value.lstrip()
    if candidate.startswith("'"):
        candidate = candidate[1:]
    return bool(candidate) and candidate[0] in "=+-@"


def safe_sheet_name(value: str, fallback: str) -> str:
    normalized = normalize_text(value)
    normalized = re.sub(r"[\[\]:*?/\\]", "_", normalized)
    return normalized[:31] or fallback
