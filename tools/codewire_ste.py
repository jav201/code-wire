"""Code-Wire language check (rule C17): is the English prose of a Markdown file written to the
measurable rules of ASD-STE100, as `Language-STE.md` sets them for this project?

Checked, per sentence of prose (paragraphs and list items; not headings, tables, code):
    S1 length       a sentence in a numbered step has 20 words or fewer; any other sentence, 25 or fewer
    S2 one step     a numbered step gives one instruction: no `;`, `, then`, `and then`
    S3 paragraph    a paragraph has 6 sentences or fewer
    S4 one word     a word that the glossary replaces is not used (glossary column "Not")
    W1 passive      a form of `be` + past participle: warning only, the check is approximate
Inline code, links and quoted literals count as one word. Errors give exit code 1; warnings do not.

    python codewire_ste.py FILE.md [FILE.md ...] --glossary Language-STE.md
"""
import argparse
import re
import sys
from pathlib import Path

STEP_MAX, TEXT_MAX, PARA_MAX = 20, 25, 6
STEP = re.compile(r"^\s*\d+\.\s+")
ITEM = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")
LITERAL = re.compile(r"`[^`]*`|\[[^\]]*\]\([^)]*\)|\"[^\"]*\"|«[^»]*»")
ABBREV = re.compile(r"\b(e\.g|i\.e|etc|vs|cf|no|fig)\.", re.I)
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"«*_])")
CHAIN = re.compile(r";|,\s*then\b|\band then\b", re.I)
PASSIVE = re.compile(r"\b(is|are|was|were|be|been|being)\s+(?:\w+ly\s+)?(\w+ed|known|done|made|given|written|read|"
                     r"found|shown|run|set|kept|left|built|sent|taken|seen|put|split|cut)\b", re.I)
WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’_/.-]*")


def load_glossary(path):
    """{word not to use: word to use}, from the `## Glossary` table: | Use | Not | Meaning |."""
    out, inside = {}, False
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            inside = line.strip().lower() == "## glossary"
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if inside and line.startswith("|") and len(cells) >= 2 and cells[0].lower() not in ("use", "") and not set(cells[0]) <= set("-: "):
            for bad in cells[1].split(","):
                if bad.strip():
                    out[bad.strip().strip("`").lower()] = cells[0].strip("`")
    return out


def blocks(text):
    """Yield (line number, is numbered step, text) for each prose paragraph or list item."""
    fenced, buf, start, step = False, [], 0, False

    def flush():
        if buf:
            yield start, step, " ".join(buf)

    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            yield from flush(); buf = []
            fenced = not fenced
            continue
        bare = line.strip()
        if fenced or not bare or bare.startswith(("#", "|", ">", "<!--")) or bare == "---":
            yield from flush(); buf = []
            continue
        if ITEM.match(line):
            yield from flush()
            buf, start, step = [ITEM.sub("", line).strip()], i, bool(STEP.match(line))
        else:
            if not buf:
                start, step = i, False
            buf.append(bare)
    yield from flush()


def sentences(text):
    masked = LITERAL.sub("LIT", text)
    dot = ""  # a private-use char: never in real text, unlike "§"
    masked = ABBREV.sub(lambda m: m.group(1) + dot, masked)   # keep "e.g." inside the sentence
    masked = re.sub(r"(\d)\.(\d)", rf"\1{dot}\2", masked)      # and "3.4"
    return [s.replace(dot, ".").strip() for s in SENTENCE_END.split(masked) if s.strip()]


def check_text(text, glossary, name="<text>"):
    """Return a list of findings: (file, line, rule, level, message)."""
    found = []
    for line, step, para in blocks(text):
        sents = sentences(para)
        if len(sents) > PARA_MAX:
            found.append((name, line, "S3", "error", f"paragraph has {len(sents)} sentences (max {PARA_MAX})"))
        limit = STEP_MAX if step else TEXT_MAX
        for s in sents:
            words = WORD.findall(s)
            if len(words) > limit:
                found.append((name, line, "S1", "error", f"{len(words)} words (max {limit}): {s[:60]}…"))
            if step and CHAIN.search(s):
                found.append((name, line, "S2", "error", f"more than one instruction: {s[:60]}…"))
            for bad, good in glossary.items():
                if re.search(rf"\b{re.escape(bad)}\b", s, re.I):
                    found.append((name, line, "S4", "error", f"use `{good}`, not `{bad}`"))
            if PASSIVE.search(s):
                found.append((name, line, "W1", "warning", f"passive voice? `{PASSIVE.search(s).group(0)}`"))
    return found


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--glossary", required=True, type=Path)
    a = ap.parse_args(argv)
    glossary = load_glossary(a.glossary)
    found = [f for p in a.files for f in check_text(p.read_text(encoding="utf-8"), glossary, str(p))]
    for name, line, rule, level, msg in found:
        print(f"{name}:{line}: {rule} {level}: {msg}")
    errors = sum(f[3] == "error" for f in found)
    print(f"{errors} errors, {len(found) - errors} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
