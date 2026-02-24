import argparse
import re
from pathlib import Path


def u(text: str) -> str:
    return text.encode("ascii").decode("unicode_escape")


DIRECT_REPLACEMENTS = [
    (u(r"dzwoni\u0105cemu"), u(r"wywo\u0142uj\u0105cemu")),
    (u(r"dzwoni\u0105cy"), u(r"wywo\u0142uj\u0105cy")),
    (u(r"go\u015b\u0107</strong>"), u(r"wywo\u0142uj\u0105cy</strong>")),
    (u(r"zwany</strong> funkcjonowa\u0107"), u(r"zwany</strong> funkcj\u0105")),
    (u(r"o\u015bwiadczenie zwrotne"), u(r"instrukcja return")),
    (u(r"wczesnym powrotem"), u(r"wczesnym zwrotem")),
    (u(r"zwr\u00f3ci\u0107 wed\u0142ug warto\u015bci"), u(r"zwracanie przez warto\u015b\u0107")),
    (u(r"zwr\u00f3ci\u0107 dzwoni\u0105cemu"), u(r"zwr\u00f3ci\u0107 wywo\u0142uj\u0105cemu")),
    (u(r"zwracana dzwoni\u0105cemu"), u(r"zwracana wywo\u0142uj\u0105cemu")),
    (u(r"pr\u00f3\u017cnia"), "void"),
    (u(r"nie powinny</em> robisz"), u(r"nie powiniene\u015b</em> robi\u0107")),
    (u(r"powiniene\u015b</em> robisz"), u(r"powiniene\u015b</em> robi\u0107")),
    (u(r"w hierarchia polimorficzna"), u(r"w hierarchii polimorficznej")),
    (u(r"to tzw <strong>"), u(r"to tzw. <strong>")),
    (u(r"to tzw <code>"), u(r"to tzw. <code>")),
    (u(r"niewiarygodnie szybko i ca\u0142y czas coraz szybciej"), u(r"bardzo szybkie i z roku na rok coraz szybsze")),
    (u(r"w szerokim zakresie odnosi si\u0119"), u(r"odnosi si\u0119 og\u00f3lnie")),
    (u(r"z wi\u0119cej ni\u017c tylko sprz\u0119t"), u(r"nie tylko ze sprz\u0119tem")),
    (u(r"komputerem komputer"), "komputerem"),
    (u(r"j\u0119zyk j\u0119zyk"), u(r"j\u0119zyk")),
    (u(r"mog\u0105 mog\u0105 by\u0107"), u(r"mog\u0105 by\u0107")),
    (u(r"SUCHY</strong> programowanie"), u(r"DRY</strong> (nie powtarzaj si\u0119)")),
]


REGEX_REPLACEMENTS = [
    # Remove stray English articles before formatted terms.
    (re.compile(r"\b(?:a|an|the)\s+(?=<strong>)", flags=re.IGNORECASE), ""),
    (re.compile(r"\b(?:a|an|the)\s+(?=<code>)", flags=re.IGNORECASE), ""),
    # Remove escaped ">" added before lesson numbers in links/titles.
    (re.compile(r"&gt;(?=(?:\d+\.\d+|\d+\.x|[A-Z]\.\d+)\b)"), ""),
]


KEYWORDS_REL_PATH = Path("cpp-tutorial/keywords-and-naming-identifiers/index.html")
KEYWORD_LIST_RE = re.compile(r"(<div id=wid[^>]*><ul[^>]*>)(.*?)(</ul></div>)", re.DOTALL)


def sync_keyword_list_with_backup(current_html: str, backup_html: str) -> str:
    current_match = KEYWORD_LIST_RE.search(current_html)
    backup_match = KEYWORD_LIST_RE.search(backup_html)
    if not current_match or not backup_match:
        return current_html

    current_list = current_match.group(2)
    backup_list = backup_match.group(2)
    if current_list == backup_list:
        return current_html

    return (
        current_html[: current_match.start(2)]
        + backup_list
        + current_html[current_match.end(2) :]
    )


def process_html_text(text: str) -> str:
    updated = text

    for old, new in DIRECT_REPLACEMENTS:
        updated = updated.replace(old, new)

    for rx, repl in REGEX_REPLACEMENTS:
        updated = rx.sub(repl, updated)

    return updated


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, help="Path to translated www.learncpp.com tree")
    parser.add_argument(
        "--backup-root",
        default="",
        help="Path to original English backup tree (used for keyword list sync)",
    )
    args = parser.parse_args()

    root = Path(args.root)
    backup_root = Path(args.backup_root) if args.backup_root else None

    files = sorted(root.rglob("*.html"))
    changed = 0

    for index, file_path in enumerate(files, start=1):
        original = file_path.read_text(encoding="utf-8", errors="ignore")
        updated = process_html_text(original)

        rel_path = file_path.relative_to(root)
        if backup_root and rel_path.as_posix() == KEYWORDS_REL_PATH.as_posix():
            backup_path = backup_root / rel_path
            if backup_path.exists():
                backup_html = backup_path.read_text(encoding="utf-8", errors="ignore")
                updated = sync_keyword_list_with_backup(updated, backup_html)

        if updated != original:
            file_path.write_text(updated, encoding="utf-8")
            changed += 1

        if index % 25 == 0 or index == len(files):
            print(f"PROGRESS {index}/{len(files)} changed={changed}")

    print(f"DONE files={len(files)} changed={changed}")


if __name__ == "__main__":
    main()
