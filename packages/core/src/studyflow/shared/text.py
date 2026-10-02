import re

def decode_escaped_text(value: str) -> str:
    return re.sub(r"\u([0-9a-fA-F]{4})", lambda match: chr(int(match.group(1), 16)), value)
