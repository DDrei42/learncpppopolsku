import argparse
import html
import json
import re
import time
from pathlib import Path

from deep_translator import GoogleTranslator


CODE_RE = re.compile(r"(<code\b[^>]*>)(.*?)(</code>)", re.IGNORECASE | re.DOTALL)
WORD_RE = re.compile(r"[A-Za-z]{2,}")
URL_RE = re.compile(r"(https?://|www\.)", re.IGNORECASE)
PL_CHARS_RE = re.compile(r"[\u0105\u0107\u0119\u0142\u0144\u00f3\u015b\u017a\u017c\u0104\u0106\u0118\u0141\u0143\u00d3\u015a\u0179\u017b]")
LEAD_WS_RE = re.compile(r"^\s*")
TRAIL_WS_RE = re.compile(r"\s*$")
BLOCK_DECOR_RE = re.compile(r"^(\s*\*+\s?)(.*)$")
MOJIBAKE_RE = re.compile(r"(Ã.|Â.|â€™|â€œ|â€|â€“|â€”|â„¢)")

EN_HINT_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "be",
    "because",
    "before",
    "both",
    "but",
    "call",
    "called",
    "can",
    "class",
    "copy",
    "create",
    "created",
    "creating",
    "destroyed",
    "directly",
    "does",
    "each",
    "else",
    "example",
    "for",
    "from",
    "function",
    "get",
    "here",
    "if",
    "in",
    "is",
    "it",
    "later",
    "legal",
    "line",
    "loop",
    "make",
    "name",
    "new",
    "not",
    "now",
    "object",
    "objects",
    "only",
    "or",
    "over",
    "pointer",
    "prevent",
    "print",
    "reference",
    "references",
    "set",
    "step",
    "still",
    "string",
    "that",
    "the",
    "these",
    "this",
    "those",
    "through",
    "to",
    "true",
    "use",
    "used",
    "using",
    "value",
    "values",
    "we",
    "when",
    "where",
    "which",
    "while",
    "with",
    "you",
    "your",
}


def split_ws(text: str):
    lead = LEAD_WS_RE.match(text).group(0)
    trail = TRAIL_WS_RE.search(text).group(0)
    core = text[len(lead) : len(text) - len(trail) if len(trail) else len(text)]
    return lead, core, trail


def is_mostly_code_like(text: str) -> bool:
    if "::" in text:
        return True
    if "<" in text or ">" in text or "{" in text or "}" in text:
        return True
    if ";" in text or "->" in text:
        return True
    if re.search(r"\b[A-Za-z_][A-Za-z0-9_]*\s*\(", text):
        return True
    return False


def english_score(text: str):
    words = WORD_RE.findall(text)
    if not words:
        return 0, 0
    lower_words = [w.lower() for w in words]
    hits = sum(1 for w in lower_words if w in EN_HINT_WORDS)
    return hits, len(words)


def looks_english(text: str) -> bool:
    t = text.strip()
    if not t or PL_CHARS_RE.search(t):
        return False

    hits, total = english_score(t)
    if hits >= 2:
        return True
    if total >= 6 and hits >= 1:
        return True

    letters = sum(ch.isalpha() for ch in t)
    return total >= 8 and hits >= 1 and (letters / max(len(t), 1)) > 0.55


def should_translate_comment(core: str) -> bool:
    t = core.strip()
    if not t:
        return False
    if len(t) < 3 or len(t) > 500:
        return False
    if URL_RE.search(t):
        return False
    if PL_CHARS_RE.search(t):
        return False

    words = WORD_RE.findall(t)
    if not words:
        return False

    english_hits, _ = english_score(t)
    letters = sum(ch.isalpha() for ch in t)
    letter_ratio = letters / max(len(t), 1)

    if is_mostly_code_like(t) and english_hits == 0 and len(words) <= 8:
        return False
    if english_hits >= 1:
        return True
    if not is_mostly_code_like(t) and len(words) >= 3 and letter_ratio > 0.65:
        return True
    if len(words) >= 5 and letter_ratio > 0.55:
        return True

    return False


def postprocess_translation(text: str) -> str:
    t = text.strip()
    if not t:
        return t

    for kw in ("if", "else", "switch", "while", "for"):
        t = re.sub(
            rf"\b(?:stwierdzenie|oświadczenie)\s+{kw}\b",
            f"instrukcja {kw}",
            t,
            flags=re.IGNORECASE,
        )
        t = re.sub(
            rf"\b(?:stwierdzenia|oświadczenia)\s+{kw}\b",
            f"instrukcje {kw}",
            t,
            flags=re.IGNORECASE,
        )

    t = re.sub(r"\bnie żyje\b", "jest martwy", t, flags=re.IGNORECASE)
    t = re.sub(r"\bnie żyją\b", "są martwe", t, flags=re.IGNORECASE)
    t = re.sub(r"\s{2,}", " ", t)
    return t.strip()


def is_bad_translation(source: str, translated: str) -> bool:
    src = source.strip()
    tr = translated.strip()

    if not tr:
        return True
    if MOJIBAKE_RE.search(tr):
        return True
    if src == tr and should_translate_comment(src):
        return True
    if looks_english(src) and looks_english(tr):
        return True
    return False


def find_comment_spans(code: str):
    spans = []
    i = 0
    n = len(code)
    state = "normal"

    while i < n:
        ch = code[i]

        if state == "normal":
            if i + 1 < n and code[i : i + 2] == "//":
                start = i + 2
                j = start
                while j < n and code[j] not in "\r\n":
                    j += 1
                spans.append((start, j, "line"))
                i = j
                continue

            if i + 1 < n and code[i : i + 2] == "/*":
                start = i + 2
                j = code.find("*/", start)
                if j == -1:
                    spans.append((start, n, "block"))
                    i = n
                else:
                    spans.append((start, j, "block"))
                    i = j + 2
                continue

            if ch == '"':
                state = "dquote"
                i += 1
                continue

            if ch == "'":
                state = "squote"
                i += 1
                continue

            if ch == "R" and i + 1 < n and code[i + 1] == '"':
                dstart = i + 2
                open_paren = code.find("(", dstart)
                if open_paren != -1:
                    delim = code[dstart:open_paren]
                    close_pat = ")" + delim + '"'
                    close_idx = code.find(close_pat, open_paren + 1)
                    if close_idx != -1:
                        i = close_idx + len(close_pat)
                        continue
                i += 1
                continue

            i += 1
            continue

        if state == "dquote":
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == '"':
                state = "normal"
            i += 1
            continue

        if state == "squote":
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == "'":
                state = "normal"
            i += 1
            continue

    return spans


def build_batches(items, max_len=3800):
    batches = []
    current = []
    current_len = len("<<<MEND>>>")

    for item in items:
        _, txt = item
        marker = f"<<<M{len(current)}>>>"
        extra = len(marker) + len(txt)

        if current and (current_len + extra > max_len):
            batches.append(current)
            current = []
            current_len = len("<<<MEND>>>")

        current.append(item)
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
        next_marker = f"<<<M{i + 1}>>>" if i + 1 < len(texts) else "<<<MEND>>>"

        start = translated.find(marker)
        if start == -1:
            return None
        start += len(marker)

        end = translated.find(next_marker, start)
        if end == -1:
            return None

        out.append(translated[start:end])

    return out


def translate_one(text: str, translator_en, translator_auto):
    last = text
    for translator in (translator_en, translator_auto):
        for attempt in range(4):
            try:
                cand = translator.translate(text)
                cand = postprocess_translation(cand)
                if not is_bad_translation(text, cand):
                    return cand
                last = cand
                break
            except Exception:
                time.sleep(1.0 * (attempt + 1))

    return postprocess_translation(last)


def translate_missing(texts, cache, translator_auto, translator_en):
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
                translated_vals = translate_group_payload(translator_auto, vals)
                if translated_vals is not None:
                    break
            except Exception:
                translated_vals = None
            time.sleep(1.2 * (attempt + 1))

        if translated_vals is None:
            translated_vals = [translate_one(t, translator_en, translator_auto) for t in vals]
        else:
            fixed_vals = []
            for src, tr in zip(vals, translated_vals):
                tr = postprocess_translation(tr)
                if is_bad_translation(src, tr):
                    tr = translate_one(src, translator_en, translator_auto)
                fixed_vals.append(tr)
            translated_vals = fixed_vals

        for i, tr in zip(idxs, translated_vals):
            cache[texts[i]] = tr


def collect_comment_units(code: str, missing_set: set, cache: dict):
    for start, end, kind in find_comment_spans(code):
        content = code[start:end]

        if kind == "block" and ("\n" in content or "\r" in content):
            for line in content.splitlines():
                body = line
                m = BLOCK_DECOR_RE.match(line)
                if m:
                    body = m.group(2)

                _, core, _ = split_ws(body)
                if should_translate_comment(core) and core not in cache:
                    missing_set.add(core)
        else:
            _, core, _ = split_ws(content)
            if should_translate_comment(core) and core not in cache:
                missing_set.add(core)


def translate_comment_content(content: str, kind: str, cache: dict) -> str:
    def translate_body(body: str) -> str:
        lead, core, trail = split_ws(body)
        if not should_translate_comment(core):
            return body
        tr = cache.get(core, core)
        return lead + tr + trail

    if kind == "block" and ("\n" in content or "\r" in content):
        out_lines = []
        for line in content.splitlines(keepends=True):
            if line.endswith("\r\n"):
                end = "\r\n"
                raw = line[:-2]
            elif line.endswith("\n"):
                end = "\n"
                raw = line[:-1]
            elif line.endswith("\r"):
                end = "\r"
                raw = line[:-1]
            else:
                end = ""
                raw = line

            m = BLOCK_DECOR_RE.match(raw)
            if m:
                prefix = m.group(1)
                body = m.group(2)
                out_lines.append(prefix + translate_body(body) + end)
            else:
                out_lines.append(translate_body(raw) + end)

        return "".join(out_lines)

    return translate_body(content)


def rewrite_code_comments(code: str, cache: dict):
    spans = find_comment_spans(code)
    if not spans:
        return code, False

    updated = code
    changed = False

    for start, end, kind in reversed(spans):
        old = updated[start:end]
        new = translate_comment_content(old, kind, cache)
        if new != old:
            updated = updated[:start] + new + updated[end:]
            changed = True

    return updated, changed


def collect_missing_from_file(path: Path, cache: dict, missing_set: set):
    text = path.read_text(encoding="utf-8", errors="ignore")
    for match in CODE_RE.finditer(text):
        code_escaped = match.group(2)
        code_decoded = html.unescape(code_escaped)
        collect_comment_units(code_decoded, missing_set, cache)


def process_file(path: Path, cache: dict):
    text = path.read_text(encoding="utf-8", errors="ignore")
    changed = False

    out = []
    last = 0
    for match in CODE_RE.finditer(text):
        out.append(text[last : match.start()])

        prefix, code_escaped, suffix = match.group(1), match.group(2), match.group(3)
        code_decoded = html.unescape(code_escaped)
        code_new, code_changed = rewrite_code_comments(code_decoded, cache)

        if code_changed:
            changed = True
            code_escaped = html.escape(code_new, quote=False)

        out.append(prefix + code_escaped + suffix)
        last = match.end()

    out.append(text[last:])

    if changed:
        path.write_text("".join(out), encoding="utf-8")

    return changed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--cache", required=True)
    parser.add_argument("--seed-cache", default="")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    root = Path(args.root)
    cache_path = Path(args.cache)
    seed_cache_path = Path(args.seed_cache) if args.seed_cache else None

    files = sorted(root.rglob("*.html"))
    if args.limit > 0:
        files = files[: args.limit]

    cache = {}
    if seed_cache_path and seed_cache_path.exists():
        try:
            cache.update(json.loads(seed_cache_path.read_text(encoding="utf-8")))
        except Exception:
            pass

    if cache_path.exists():
        try:
            cache.update(json.loads(cache_path.read_text(encoding="utf-8")))
        except Exception:
            pass

    stale_keys = []
    for k, v in cache.items():
        if isinstance(k, str) and isinstance(v, str) and is_bad_translation(k, v):
            stale_keys.append(k)

    for k in stale_keys:
        cache.pop(k, None)

    missing_set = set()
    for i, f in enumerate(files, 1):
        collect_missing_from_file(f, cache, missing_set)
        if i % 40 == 0 or i == len(files):
            print(f"SCAN {i}/{len(files)} missing={len(missing_set)}")

    if missing_set:
        translator_auto = GoogleTranslator(source="auto", target="pl")
        translator_en = GoogleTranslator(source="en", target="pl")
        missing_list = sorted(missing_set)
        translate_missing(missing_list, cache, translator_auto, translator_en)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        print(f"TRANSLATED missing={len(missing_set)} cache={len(cache)}")

    changed = 0
    for i, f in enumerate(files, 1):
        try:
            if process_file(f, cache):
                changed += 1
        except Exception as exc:
            print(f"ERROR {f}: {exc}")

        if i % 25 == 0 or i == len(files):
            cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
            print(f"WRITE {i}/{len(files)} changed={changed}")

    cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    print(f"DONE files={len(files)} changed={changed} cache={len(cache)}")


if __name__ == "__main__":
    main()
