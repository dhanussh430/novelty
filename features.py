"""Technical feature + keyword extraction (pure Python, no model downloads)."""
import re
from collections import Counter

STOPWORDS = set("""
a an the and or but if then else of in on at by for to from with without within into onto over under about above
below between among through during before after as is are was were be been being am do does did done have has had
having it its this that these those there here which who whom whose what when where why how not no nor so than too
very can could should would may might must shall will just also such each every any all some more most other
another own same only both either neither via per using use used uses based wherein whereby comprising comprises
comprise comprised including includes include included present invention embodiment embodiments provided provide
provides providing allows allow allowing able our we you your their them they he she his her i me my one two
system systems method methods device devices apparatus approach way thing things kind type etc e g ie eg new novel
improved improve improves
""".split())

BOUNDARY_RE = re.compile(
    r"[.;:!?\n()\[\]]|,|\b(?:and|or|with|using|which|that|wherein|including|by|for|to|via|while|then|so|when|if|"
    r"whereby|such as|based on|in order to|thereby|where|so that|allowing|enabling)\b",
    re.I,
)
WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-]*")

_SUFFIXES = ("ingly", "edly", "ations", "ation", "ments", "ment", "ness", "ing", "ies", "ed", "es", "s", "ly")


def stem(word: str) -> str:
    w = word.lower().strip("-")
    for suf in _SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[:-3] + "y" if suf == "ies" else w[: -len(suf)]
    return w


def tokenize(text: str) -> list:
    """Lower-cased content words (stopwords and tiny tokens removed)."""
    return [w for w in (m.group(0).lower() for m in WORD_RE.finditer(text or "")) if w not in STOPWORDS and len(w) > 2]


def stems(text: str) -> list:
    return [stem(t) for t in tokenize(text)]


def extract_features(text: str, max_features: int = 12) -> list:
    """Split the description into short technical phrases (one candidate feature per clause)."""
    features, seen = [], set()
    for frag in BOUNDARY_RE.split(text or ""):
        if not frag:
            continue
        words = WORD_RE.findall(frag)
        while words and words[0].lower() in STOPWORDS:
            words.pop(0)
        while words and words[-1].lower() in STOPWORDS:
            words.pop()
        content = [w for w in words if w.lower() not in STOPWORDS and len(w) > 2]
        if not content or (len(content) == 1 and len(content[0]) < 4):
            continue
        phrase = " ".join(words[:7])
        key = frozenset(stem(w) for w in content)
        if key in seen:
            continue
        seen.add(key)
        features.append(phrase)
        if len(features) >= max_features:
            break
    return features


def extract_keywords(text: str, max_keywords: int = 10) -> list:
    """Most informative single terms: frequency first, then length, then order of appearance."""
    toks = tokenize(text)
    counts, surface, first = Counter(), {}, {}
    for i, t in enumerate(toks):
        s = stem(t)
        counts[s] += 1
        surface.setdefault(s, t)
        first.setdefault(s, i)
    ranked = sorted(counts, key=lambda s: (-counts[s], -len(surface[s]), first[s]))
    return [surface[s] for s in ranked[:max_keywords]]


def build_queries(features: list, keywords: list, max_queries: int = 3) -> list:
    """Several search strings of different breadth (broad queries often return nothing on strict engines)."""
    cands = []
    if keywords:
        cands.append(" ".join(keywords[:6]))
        cands.append(" ".join(keywords[:4]))
    for f in features[:2]:
        words = tokenize(f)[:5]
        if words:
            cands.append(" ".join(words))
    out = []
    for q in cands:
        if q and q not in out:
            out.append(q)
    return out[:max_queries]


def format_idea_features(features: list) -> str:
    """Single-line label used in the UI, exports and the PDF report."""
    return "Idea Features: " + ("; ".join(features) if features else "none detected")


def merge_features(custom: list, auto: list, limit: int = 16) -> list:
    """User features first, then automatic ones that add something new (de-duplicated by stems)."""
    out, seen = [], set()
    for f in list(custom) + list(auto):
        f = " ".join((f or "").split())
        key = frozenset(stem(w) for w in tokenize(f))
        if f and key and key not in seen:
            seen.add(key)
            out.append(f)
    return out[:limit]
