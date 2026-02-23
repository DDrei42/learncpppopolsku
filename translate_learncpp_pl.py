import argparse
import html
import json
import re
import time
from pathlib import Path

from deep_translator import GoogleTranslator

SKIP_TAGS = {"script", "style", "pre", "code", "textarea", "svg", "math"}
ATTRS_TO_TRANSLATE = {"title", "alt", "placeholder"}

TAG_SPLIT_RE = re.compile(r"(<[^>]+>)", re.DOTALL)
START_TAG_RE = re.compile(r"^<\s*([a-zA-Z0-9:_-]+)\b")
END_TAG_RE = re.compile(r"^<\s*/\s*([a-zA-Z0-9:_-]+)\b")
ATTR_RE = re.compile(
    r"(?P<prefix>\b(?:title|alt|placeholder)\s*=\s*)(?P<quote>['\"])(?P<value>.*?)(?P=quote)",
    re.IGNORECASE | re.DOTALL,
)
URL_RE = re.compile(r"^(https?:|mailto:|tel:|www\.)", re.IGNORECASE)
HAS_LETTER_RE = re.compile(r"[A-Za-zÀ-ž]")
LEAD_WS_RE = re.compile(r"^\s*")
TRAIL_WS_RE = re.compile(r"\s*$")


def should_translate(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if URL_RE.search(t):
        return False
    if t.startswith("{{") and t.endswith("}}"):
        return False
    if not HAS_LETTER_RE.search(t):
        return False
    return True


def split_ws(text: str):
    lead = LEAD_WS_RE.match(text).group(0)
    trail = TRAIL_WS_RE.search(text).group(0)
    core = text[len(lead) : len(text) - len(trail) if len(trail) else len(text)]
    return lead, core, trail


def escape_html_text(text: str) -> str:
    return html.escape(text, quote=False)


def escape_attr_value(text: str) -> str:
    return html.escape(text, quote=True)


def parse_tag_name(token: str):
    if token.startswith("<!--") or token.startswith("<!") or token.startswith("<?"):
        return None, None
    m_end = END_TAG_RE.match(token)
    if m_end:
        return "end", m_end.group(1).lower()
    m_start = START_TAG_RE.match(token)
    if m_start:
        return "start", m_start.group(1).lower()
    return None, None


def build_batches(items, max_len=3800):
    batches = []
    current = []
    current_len = len("<<<MEND>>>")
    for item in items:
        idx, txt = item
        marker = f"<<<M{len(current)}>>>"
        extra = len(marker) + len(txt)
        if current and (current_len + extra > max_len):
            batches.append(current)
            current = []
            current_len = len("<<<MEND>>>")
            marker = f"<<<M0>>>"
            extra = len(marker) + len(txt)
        current.append((idx, txt))
        current_len += extra
    if current:
        batches.append(current)
    return batches


def translate_group_payload(translator, texts):
    payload = "".join(f"<<<M{i}>>>{t}" for i, t in enumerate(texts)) + "<<<MEND>>>"
    translated = translator.translate(payload)

    if "<<<MEND>>>" not in translated:
        return None

    out = []
    for i in range(len(texts)):
        marker = f"<<<M{i}>>>"
        next_marker = f"<<<M{i+1}>>>" if i + 1 < len(texts) else "<<<MEND>>>"
        start = translated.find(marker)
        if start == -1:
            return None
        start += len(marker)
        end = translated.find(next_marker, start)
        if end == -1:
            return None
        out.append(translated[start:end])
    return out


def translate_missing(texts, cache, translator):
    missing = [(i, t) for i, t in enumerate(texts) if t not in cache]
    if not missing:
        return

    batches = build_batches(missing)
    for batch in batches:
        idxs = [i for i, _ in batch]
        vals = [t for _, t in batch]

        translated_vals = None
        for attempt in range(5):
            try:
                translated_vals = translate_group_payload(translator, vals)
                if translated_vals is not None:
                    break
            except Exception:
                translated_vals = None
            time.sleep(1.2 * (attempt + 1))

        if translated_vals is None:
            translated_vals = []
            for t in vals:
                tr = None
                for attempt in range(5):
                    try:
                        tr = translator.translate(t)
                        break
                    except Exception:
                        time.sleep(1.2 * (attempt + 1))
                if tr is None:
                    tr = t
                translated_vals.append(tr)

        for i, tr in zip(idxs, translated_vals):
            cache[texts[i]] = tr


def process_file(path: Path, cache, translator):
    original = path.read_text(encoding="utf-8", errors="ignore")
    parts = TAG_SPLIT_RE.split(original)
    changed = False

    skip_stack = []
    text_entries = []
    attr_entries = []

    for idx, token in enumerate(parts):
        if idx % 2 == 1:
            tag_type, tag_name = parse_tag_name(token)

            if tag_type == "start" and tag_name in SKIP_TAGS and not token.rstrip().endswith("/>"):
                skip_stack.append(tag_name)
            elif tag_type == "end" and skip_stack and tag_name == skip_stack[-1]:
                skip_stack.pop()

            if not skip_stack:
                for m in ATTR_RE.finditer(token):
                    attr_name = m.group("prefix").split("=")[0].strip().lower()
                    if attr_name not in ATTRS_TO_TRANSLATE:
                        continue
                    raw_val = m.group("value")
                    val = html.unescape(raw_val)
                    if should_translate(val):
                        attr_entries.append((idx, m.start("value"), m.end("value"), raw_val, val))
            continue

        if skip_stack:
            continue

        text = token
        if not should_translate(html.unescape(text)):
            continue

        decoded = html.unescape(text)
        lead, core, trail = split_ws(decoded)
        if not should_translate(core):
            continue

        text_entries.append((idx, lead, core, trail))

    if not text_entries and not attr_entries:
        return False

    to_translate = [core for _, _, core, _ in text_entries] + [val for *_, val in attr_entries]
    translate_missing(to_translate, cache, translator)

    # Apply text replacements
    for idx, lead, core, trail in text_entries:
        tr = cache.get(core, core)
        new_text = lead + escape_html_text(tr) + trail
        if parts[idx] != new_text:
            parts[idx] = new_text
            changed = True

    # Apply attribute replacements (right-to-left per token)
    attrs_by_token = {}
    offset_base = len(text_entries)
    for j, entry in enumerate(attr_entries):
        idx, start, end, raw_val, val = entry
        tr = cache.get(val, val)
        tr_esc = escape_attr_value(tr)
        attrs_by_token.setdefault(idx, []).append((start, end, tr_esc))

    for idx, edits in attrs_by_token.items():
        token = parts[idx]
        edits.sort(key=lambda x: x[0], reverse=True)
        new_token = token
        for start, end, rep in edits:
            new_token = new_token[:start] + rep + new_token[end:]
        if new_token != token:
            parts[idx] = new_token
            changed = True

    if changed:
        path.write_text("".join(parts), encoding="utf-8")

    return changed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--cache", required=True)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    root = Path(args.root)
    cache_path = Path(args.cache)

    files = sorted(root.rglob("*.html"))
    if args.limit > 0:
        files = files[: args.limit]

    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    else:
        cache = {}

    translator = GoogleTranslator(source="en", target="pl")

    changed = 0
    for i, f in enumerate(files, 1):
        try:
            if process_file(f, cache, translator):
                changed += 1
        except Exception as e:
            print(f"ERROR {f}: {e}")

        if i % 10 == 0 or i == len(files):
            cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
            print(f"PROGRESS {i}/{len(files)} changed={changed} cache={len(cache)}")

    cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    print(f"DONE files={len(files)} changed={changed} cache={len(cache)}")


if __name__ == "__main__":
    main()
