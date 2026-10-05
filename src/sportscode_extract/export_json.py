import json
import re


def safe_name(name):
    value = re.sub(r'[/\\\x00-\x1f\x7f]', '', str(name)).strip().strip('.')
    return value[:160] or 'playlist'


def redact(value):
    if isinstance(value, dict):
        return {key: None if key in ('path', 'localPath') and isinstance(item, str) and (item.startswith('/') or item.startswith('~')) else redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
