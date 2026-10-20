"""Lightweight, dependency-free text analytics for ticket subjects and messages.

Used by the Reports dashboard. Everything here is a pure function over strings so
it can be unit-tested without a database. Handles English, French and Arabic
(the languages Intermedic customers actually write in) with small built-in
stop-word lists rather than pulling in NLTK/spaCy.
"""
import re
from collections import Counter

# ── Stop words ────────────────────────────────────────────────────────────────

_EN = """
a about above after again against all am an and any are aren't as at be because been before being below
between both but by can can't cannot could couldn't did didn't do does doesn't doing don't down during each
few for from further had hadn't has hasn't have haven't having he her here hers herself him himself his how
i i'm i've if in into is isn't it it's its itself just let's me more most mustn't my myself no nor not now of
off on once only or other ought our ours ourselves out over own same shan't she should shouldn't so some such
than that that's the their theirs them themselves then there there's these they they're this those through to
too under until up very was wasn't we we're were weren't what what's when where which while who whom why will
with won't would wouldn't you you're your yours yourself yourselves also us may might must shall yet via per
etc i'd i'll we'll we've they've you've you'll he's she's ok okay yes yeah one two three get got getting
"""
_FR = """
au aux avec ce ces dans de des du elle en et eux il ils je la le les leur lui ma mais me même mes moi mon ne nos
notre nous on ou par pas pour qu que qui sa se ses son sur ta te tes toi ton tu un une vos votre vous est sont
été être avoir ai as avons avez ont était cette cet ceci cela ça donc alors comme très plus aussi bien fait faire
peut sans sous chez entre leurs quand tout tous toute toutes car si ni dont où après avant depuis pendant
"""
_AR = """
في من على إلى الى عن مع هذا هذه ذلك تلك التي الذي الذين هو هي هم أن ان إن لا ما لم لن قد كان كانت يكون
كل بعد قبل عند أو او ثم حتى بين لكن أي اي هل نحن انا أنا انت أنت يا تم وقد وفي ومن وعلى
"""
# Greetings, sign-offs, email plumbing and support boilerplate — present in nearly
# every ticket, so they say nothing about what the case is about.
_NOISE = """
hi hello dear sir madam mr mrs ms team regards best kind warm thanks thank thx please kindly hope well good
morning afternoon evening day sincerely cordially cordialement merci bonjour bonsoir salut madame monsieur
email mail sent fwd fw re cc bcc subject attached attachment attachments find below following see image png jpg
jpeg gif cid nbsp mailto http https www com net org regarding need needs needed want like know check help support
ticket tickets intermedic issue problem urgent asap still again already since today yesterday now
"""
STOPWORDS = frozenset(w for block in (_EN, _FR, _AR, _NOISE) for w in block.split())
_EN_SET = frozenset(_EN.split())
_FR_SET = frozenset(_FR.split())

# ── Cleaning ──────────────────────────────────────────────────────────────────

_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.I)
_EMAIL_RE = re.compile(r"\S+@\S+\.\S+")
# Lines that start the quoted part of an email reply (Outlook, Gmail, French clients).
_REPLY_HEADER_RE = re.compile(
    r"^\s*(?:-{2,}\s*original message\s*-{2,}|-{2,}\s*message d'origine\s*-{2,}"
    r"|on\b.{0,200}\bwrote:|le\b.{0,200}\ba écrit\s*:|from:\s.*|de\s*:\s.*|sent from my\b.*|_{8,})\s*$",
    re.I | re.M,
)
# Lines that start a signature block.
_SIGNOFF_RE = re.compile(
    r"^\s*(?:(?:best|kind|warm|many)\s+regards|regards|sincerely|cordialement|bien à vous"
    r"|(?:many\s+)?thanks?(?:\s+you)?(?:\s+(?:very much|a lot|in advance))?)[\s,.!]*$",
    re.I | re.M,
)
_WORD_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)?")          # words incl. numbers, for counting
_TOKEN_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?")    # alphabetic tokens, for keywords
_ARABIC_RE = re.compile(r"[؀-ۿ]")
_LATIN_RE = re.compile(r"[A-Za-zÀ-ÿ]")


def strip_quoted(text: str, is_reply: bool = True) -> str:
    """Drop quoted history and signature from an email-ish message body.

    The first message of a ticket is not treated as a reply: forwarded emails put
    the real content *below* a "From:" header, so only `>`-quoted lines go.
    """
    if not text:
        return ""
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith(">")]
    text = "\n".join(lines)
    if is_reply:
        m = _REPLY_HEADER_RE.search(text)
        if m and m.start() > 0:
            text = text[: m.start()]
    m = _SIGNOFF_RE.search(text)
    if m and m.start() > 40:
        text = text[: m.start()]
    return text.strip()


def word_count(text: str) -> int:
    return len(_WORD_RE.findall(text or ""))


def tokenize(text: str) -> list[str]:
    """Lower-cased alphabetic tokens with URLs and email addresses removed."""
    if not text:
        return []
    text = _EMAIL_RE.sub(" ", _URL_RE.sub(" ", text))
    return [t.replace("’", "'") for t in _TOKEN_RE.findall(text.lower())]


def content_terms(tokens: list[str]) -> list[str]:
    return [t for t in tokens if len(t) >= 3 and t not in STOPWORDS]


_CLAUSE_RE = re.compile(r"[.,;:!?()\[\]{}\"“”<>|/\\\n\r\t]+|\s[-–—]\s")


def bigrams(tokens: list[str]) -> list[str]:
    """Adjacent pairs where neither word is a stop word (no bridging over removed words)."""
    out = []
    for a, b in zip(tokens, tokens[1:]):
        if len(a) >= 3 and len(b) >= 3 and a not in STOPWORDS and b not in STOPWORDS and a != b:
            out.append(f"{a} {b}")
    return out


def phrases(text: str) -> list[str]:
    """Bigrams taken within clauses, so "not working, ORA-…" never yields "working ora"."""
    out = []
    for clause in _CLAUSE_RE.split(_EMAIL_RE.sub(" ", _URL_RE.sub(" ", text or ""))):
        out.extend(bigrams(tokenize(clause)))
    return out


def detect_language(text: str, tokens: list[str] | None = None) -> str:
    """Coarse language guess: Arabic / French / English / Unknown."""
    if not text:
        return "Unknown"
    arabic = len(_ARABIC_RE.findall(text))
    latin = len(_LATIN_RE.findall(text))
    if arabic + latin < 12:
        return "Unknown"
    if arabic > latin:
        return "Arabic"
    tokens = tokens if tokens is not None else tokenize(text)
    en = sum(1 for t in tokens if t in _EN_SET)
    fr = sum(1 for t in tokens if t in _FR_SET)
    if en == 0 and fr == 0:
        return "Unknown"
    return "French" if fr > en else "English"


# ── Tone signals ──────────────────────────────────────────────────────────────

def _phrase_re(phrases):
    alt = "|".join(re.escape(p).replace(r"\ ", r"\s+") for p in sorted(phrases, key=len, reverse=True))
    return re.compile(rf"(?<![\w])(?:{alt})(?![\w])", re.I)


URGENCY_TERMS = [
    "urgent", "urgently", "asap", "as soon as possible", "emergency", "critical", "immediately",
    "right away", "outage", "system down", "is down", "went down", "not working at all", "stopped working",
    "production down", "blocking", "blocked", "patients waiting", "cannot work",
    "urgence", "au plus vite", "bloquant", "bloqué", "critique", "en panne",
]
FRUSTRATION_TERMS = [
    "still", "again", "no response", "no reply", "no answer", "any update", "follow up", "following up",
    "reminder", "repeatedly", "second time", "third time", "several times", "many times", "unacceptable",
    "not resolved", "same issue", "same problem", "not fixed", "keeps happening", "still not",
    "toujours", "encore", "relance", "pas résolu",
]
_URGENCY_RE = _phrase_re(URGENCY_TERMS)
_FRUSTRATION_RE = _phrase_re(FRUSTRATION_TERMS)


def urgency_hits(text: str) -> list[str]:
    return [m.group(0).lower() for m in _URGENCY_RE.finditer(text or "")]


def frustration_hits(text: str) -> list[str]:
    return [m.group(0).lower() for m in _FRUSTRATION_RE.finditer(text or "")]


# ── Technical references (error codes, exceptions) ───────────────────────────

# (pattern, upper-case the match so "Error 1045" and "error 1045" count together)
_CODE_PATTERNS = [
    (re.compile(r"\b[A-Z]{2,6}-\d{3,6}\b"), False),                                  # ORA-12154
    (re.compile(r"\b[A-Z][A-Za-z]{2,}(?:Exception|Error)\b"), False),                # NullPointerException
    (re.compile(r"\bHTTP\s?[1-5]\d\d\b", re.I), True),                                # HTTP 500
    (re.compile(r"\b(?:error|err|erreur)\s*(?:code|no\.?|#)?\s*[:#]?\s*\d{3,6}\b", re.I), True),  # error 1045
]


def error_codes(text: str) -> set[str]:
    found = set()
    for pat, upper in _CODE_PATTERNS:
        for m in pat.finditer(text or ""):
            code = re.sub(r"\s+", " ", m.group(0)).strip()
            found.add(code.upper() if upper else code)
    return found


# ── Document-frequency counter ────────────────────────────────────────────────

class TermCounter:
    """Counts how many documents (tickets) mention each term, so one long email
    thread can't dominate the keyword list."""

    def __init__(self):
        self.doc_freq = Counter()
        self.docs = 0

    def add(self, terms):
        self.docs += 1
        self.doc_freq.update(set(terms))

    def top(self, n):
        return self.doc_freq.most_common(n)
