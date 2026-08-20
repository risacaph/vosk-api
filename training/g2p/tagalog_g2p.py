#!/usr/bin/env python3
"""Grapheme-to-phoneme conversion for Filipino (Tagalog).

Why this exists
---------------
Building a small Filipino Vosk model with a lookahead graph needs a
pronunciation lexicon. The lexicon behind vosk-model-tl-ph-generic-0.6 was
derived from the licensed KIT/CMU Tagalog corpus and is not redistributable,
so the lexicon has to be regenerated from scratch. Filipino orthography is
close to phonemic, which makes a rule-based G2P practical where it would not
be for English.

What it can and cannot recover
------------------------------
Filipino spelling does not write two things that are phonemically real:

  * **Glottal stop.** Word-final glottal stop is never written. "batà" (child)
    and "bata" (bathrobe) are both spelled "bata". Word-internal glottal stop
    *is* recoverable, because modern orthography writes it as a vowel sequence
    ("maaari") or a hyphen ("pag-asa").
  * **Stress.** Unwritten, and it distinguishes minimal pairs.

Neither is guessable from spelling alone. Rather than pick one reading, pass
``variants=True`` (or ``--variants``) to emit both, which is the usual way to
handle it for ASR: the decoder picks whichever matches the audio.

Loanword letters are ambiguous in a different way. Speakers vary between the
Spanish/English phone and its nativised counterpart — "video" as V or B,
"telepono" as F or P. Variant mode emits both of those too.

Usage
-----
    tagalog_g2p.py bata mga pag-asa          # pronounce words
    tagalog_g2p.py --variants bata           # all readings
    echo "aso pusa" | tagalog_g2p.py -       # read from stdin
    tagalog_g2p.py --dict-dir data/local/dict --wordlist words.txt
"""

import argparse
import re
import sys
import unicodedata

# --- Phone inventory -------------------------------------------------------
#
# Native Filipino: 16 consonants + 5 vowels. Q is the glottal stop, NG the
# velar nasal. Kept ASCII and uppercase so Kaldi tooling is happy.

VOWELS = ["A", "E", "I", "O", "U"]

NATIVE_CONSONANTS = [
    "P", "B", "T", "D", "K", "G", "Q",
    "M", "N", "NG",
    "S", "H", "L", "R", "W", "Y",
]

# Only reachable through Spanish and English borrowings, which early-grade
# reading passages are full of ("silya", "telepono", "tsinelas").
LOAN_CONSONANTS = ["F", "V", "Z", "SH", "CH", "JH"]

PHONES = VOWELS + NATIVE_CONSONANTS + LOAN_CONSONANTS
SILENCE_PHONES = ["SIL", "SPN"]

# Letters whose reading Filipino speakers genuinely vary on. The first entry
# is the default; the rest are offered in variant mode.
#
#   f, v  The 1987 Filipino alphabet includes both, and speakers do produce
#         them in loans, but the nativised P/B is equally common. "Filipino"
#         and "Pilipino" are the canonical pair.
#   z     Written in loans and proper nouns, but /z/ is marginal in Filipino,
#         so S is the default reading. "Quezon" is /keson/.
#   j     Spanish-derived j is /h/ ("Jose", "Juan") and that is the common
#         case in Filipino text; English-derived /dʒ/ is the alternative.
AMBIGUOUS_GRAPHEMES = {
    "f": (["F"], [["P"]]),
    "v": (["V"], [["B"]]),
    "z": (["S"], [["Z"]]),
    "j": (["H"], [["JH"]]),
}

# --- Whole-word exceptions -------------------------------------------------
#
# Words whose spelling genuinely lies about their pronunciation. This list is
# deliberately tiny; anything that can be handled by rule is.

EXCEPTIONS = {
    # The plural marker, by far the most common irregular in Filipino text.
    # Spelled "mga", said "manga".
    "mga": [["M", "A", "NG", "A"]],
    # The linker, spelled "ng", said "nang".
    "ng": [["N", "A", "NG"]],
    # Written as a single letter but read as its letter name in running text.
    "at": [["Q", "A", "T"]],
}

_SYLLABLE_BREAK = "-"  # internal marker, never emitted


class G2PError(ValueError):
    """Raised for input the rules cannot honestly convert."""


def normalise(word):
    """Lowercase, strip diacritics we do not model, keep letters and hyphens.

    Accented vowels appear in dictionaries to mark stress and final glottal
    stop ("batà", "áso"). We drop the accent here and let variant mode cover
    the glottal reading, rather than pretending we can read stress off text
    that almost never carries it.
    """
    word = unicodedata.normalize("NFD", word.strip().lower())
    # Keep n-with-tilde: it is a real grapheme, not a stress mark.
    word = "".join(
        c for c in word
        if not unicodedata.combining(c) or c == "̃"
    )
    return unicodedata.normalize("NFC", word)


def _tokenise(word):
    """Split spelling into (grapheme, default_phones, alternatives) triples.

    Longest match first. ``alternatives`` is a list of other phone sequences
    the same letter can legitimately take; it is empty for the many letters
    Filipino spells unambiguously.
    """
    out = []
    i = 0
    n = len(word)

    while i < n:
        c = word[i]
        nxt = word[i + 1] if i + 1 < n else ""
        nxt2 = word[i + 2] if i + 2 < n else ""

        # -- trigraph / digraph consonants --
        if c == "n" and nxt == "g":
            # "ng" is one phoneme. In "sanggol" the spelling is n-g-g, so the
            # third letter stays a separate G.
            out.append(("ng", ["NG"], []))
            i += 2
            continue
        if c == "t" and nxt == "s":
            out.append(("ts", ["CH"], []))
            i += 2
            continue
        if c == "c" and nxt == "h":
            out.append(("ch", ["CH"], []))
            i += 2
            continue
        if c == "s" and nxt == "h":
            out.append(("sh", ["SH"], []))
            i += 2
            continue
        if c == "l" and nxt == "l":
            # Spanish loans: "apellido". Native spelling would use "ly".
            out.append(("ll", ["L", "Y"], []))
            i += 2
            continue
        if c == "q" and nxt == "u":
            # "Quezon" -> K, "quatro" -> K W
            if nxt2 in "ei":
                out.append(("qu", ["K"], []))
            else:
                out.append(("qu", ["K", "W"], []))
            i += 2
            continue
        if c == "g" and nxt == "u" and nxt2 in "ei":
            # Spanish "gue"/"gui": the u is silent.
            out.append(("gu", ["G"], []))
            i += 2
            continue

        # -- context-dependent single letters --
        if c == "c":
            out.append(("c", ["S"] if nxt in "ei" else ["K"], []))
            i += 1
            continue
        if c == "ñ":
            out.append(("ñ", ["N", "Y"], []))
            i += 1
            continue
        if c == "x":
            out.append(("x", ["K", "S"], []))
            i += 1
            continue
        if c == "q":
            # Bare q without u is not native spelling; treat as K.
            out.append(("q", ["K"], []))
            i += 1
            continue

        # -- syllable break --
        if c in "-‐‑":
            out.append((_SYLLABLE_BREAK, [_SYLLABLE_BREAK], []))
            i += 1
            continue

        # -- plain letters --
        if c in AMBIGUOUS_GRAPHEMES:
            default, alts = AMBIGUOUS_GRAPHEMES[c]
            out.append((c, list(default), [list(a) for a in alts]))
            i += 1
            continue

        simple = {
            "a": "A", "e": "E", "i": "I", "o": "O", "u": "U",
            "p": "P", "b": "B", "t": "T", "d": "D", "k": "K", "g": "G",
            "m": "M", "n": "N", "s": "S", "h": "H", "l": "L", "r": "R",
            "w": "W", "y": "Y",
        }
        if c in simple:
            out.append((c, [simple[c]], []))
            i += 1
            continue

        raise G2PError("no rule for %r in %r" % (c, word))

    return out


def _insert_glottal_stops(phones):
    """Add Q where Filipino requires a glottal onset.

    Every syllable that would otherwise start with a vowel takes one: at the
    start of a word ("aso"), between two vowels ("maaari"), and after an
    explicit hyphen ("pag-asa").
    """
    out = []
    forced_break = False

    for phone in phones:
        if phone == _SYLLABLE_BREAK:
            forced_break = True
            continue

        if phone in VOWELS:
            at_start = not out
            after_vowel = bool(out) and out[-1] in VOWELS
            if at_start or after_vowel or forced_break:
                out.append("Q")

        out.append(phone)
        forced_break = False

    return out


def _expand_tokens(tokens, variants):
    """Turn tokens into one phone sequence, or all legitimate readings."""
    seqs = [[]]
    for _grapheme, default, alts in tokens:
        options = [default] + alts if (variants and alts) else [default]
        if len(options) == 1:
            for seq in seqs:
                seq.extend(options[0])
        else:
            seqs = [seq + list(opt) for seq in seqs for opt in options]
    return seqs


def pronounce(word, variants=False):
    """Return a list of pronunciations, each a list of phones.

    With ``variants=False`` the single most likely reading is returned. With
    ``variants=True`` the ambiguities Filipino spelling does not encode are
    enumerated: unwritten final glottal stop, and loan-phone nativisation.
    """
    normalised = normalise(word)
    if not normalised:
        raise G2PError("empty word")

    if normalised in EXCEPTIONS:
        return [list(p) for p in EXCEPTIONS[normalised]]

    if not re.fullmatch(r"[a-zñ\-‐‑]+", normalised):
        raise G2PError(
            "%r contains characters this G2P does not handle; digits and "
            "symbols must be spelled out before lookup" % word
        )

    tokens = _tokenise(normalised)
    forms = [_insert_glottal_stops(seq)
             for seq in _expand_tokens(tokens, variants)]
    forms = [f for f in forms if f]

    if not forms:
        raise G2PError("%r produced no phones" % word)

    if not variants:
        return forms[:1]

    # Unwritten word-final glottal stop. Only vowel-final words can take one.
    if forms[0][-1] in VOWELS:
        forms = forms + [f + ["Q"] for f in forms]

    # Preserve order, drop duplicates.
    seen = set()
    unique = []
    for f in forms:
        key = tuple(f)
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def write_dict_dir(path, words, variants=False, unk_word="[unk]"):
    """Write a Kaldi dict directory: the files prepare_dict.sh would produce.

    Returns (num_entries, failures) where failures is a list of
    (word, reason) for anything that could not be converted.
    """
    import os

    os.makedirs(path, exist_ok=True)
    entries = []
    failures = []
    used_phones = set()

    for word in words:
        try:
            for prons in pronounce(word, variants=variants):
                entries.append((word, prons))
                used_phones.update(prons)
        except G2PError as exc:
            failures.append((word, str(exc)))

    with open(os.path.join(path, "lexicon.txt"), "w", encoding="utf-8") as f:
        f.write("!SIL SIL\n")
        # A single SPN is a placeholder, not a garbage model. See README:
        # the phone loop for [unk] is built by Kaldi's make_unk_lm.sh, and
        # without it a passage-constrained decoder cannot reject off-passage
        # speech.
        f.write("%s SPN\n" % unk_word)
        for word, prons in sorted(set((w, tuple(p)) for w, p in entries)):
            f.write("%s %s\n" % (word, " ".join(prons)))

    with open(os.path.join(path, "nonsilence_phones.txt"), "w", encoding="utf-8") as f:
        for phone in PHONES:
            if phone in used_phones:
                f.write(phone + "\n")

    with open(os.path.join(path, "silence_phones.txt"), "w", encoding="utf-8") as f:
        for phone in SILENCE_PHONES:
            f.write(phone + "\n")

    with open(os.path.join(path, "optional_silence.txt"), "w", encoding="utf-8") as f:
        f.write("SIL\n")

    # Filipino has no lexical tone and no marked stress in the phone set, so
    # there are no extra questions to ask.
    with open(os.path.join(path, "extra_questions.txt"), "w", encoding="utf-8") as f:
        f.write("")

    return len(entries), failures


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Filipino (Tagalog) grapheme-to-phoneme conversion.",
    )
    parser.add_argument("words", nargs="*",
                        help="words to pronounce, or - to read stdin")
    parser.add_argument("--variants", action="store_true",
                        help="emit every reading spelling leaves ambiguous "
                             "(final glottal stop, loan-phone nativisation)")
    parser.add_argument("--wordlist",
                        help="file with one word per line")
    parser.add_argument("--dict-dir",
                        help="write a Kaldi dict directory here instead of "
                             "printing pronunciations")
    parser.add_argument("--phones", action="store_true",
                        help="print the phone inventory and exit")
    args = parser.parse_args(argv)

    if args.phones:
        print("# vowels");            print("\n".join(VOWELS))
        print("# native consonants"); print("\n".join(NATIVE_CONSONANTS))
        print("# loan consonants");   print("\n".join(LOAN_CONSONANTS))
        print("# silence");           print("\n".join(SILENCE_PHONES))
        return 0

    words = []
    if args.wordlist:
        with open(args.wordlist, encoding="utf-8") as f:
            words.extend(line.strip() for line in f if line.strip())
    for word in args.words:
        if word == "-":
            words.extend(sys.stdin.read().split())
        else:
            words.append(word)

    if not words:
        parser.error("no words given; pass words, --wordlist, or -")

    if args.dict_dir:
        count, failures = write_dict_dir(args.dict_dir, words,
                                         variants=args.variants)
        print("wrote %d lexicon entries to %s" % (count, args.dict_dir))
        if failures:
            print("%d words could not be converted:" % len(failures),
                  file=sys.stderr)
            for word, reason in failures:
                print("  %s: %s" % (word, reason), file=sys.stderr)
            return 1
        return 0

    status = 0
    for word in words:
        try:
            for prons in pronounce(word, variants=args.variants):
                print("%s\t%s" % (word, " ".join(prons)))
        except G2PError as exc:
            print("%s\t<error: %s>" % (word, exc), file=sys.stderr)
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
