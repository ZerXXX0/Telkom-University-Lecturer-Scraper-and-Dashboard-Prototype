import re

def normalize_name(name: str) -> str:
    if not name: return ""
    name = re.sub(r'[^a-zA-Z\s]', '', name)
    return ' '.join(name.split()).title()

def normalize_keyword(keyword: str) -> str:
    if not keyword: return ""
    return keyword.lower().strip()
