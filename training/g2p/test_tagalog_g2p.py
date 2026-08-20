#!/usr/bin/env python3
"""Tests for the Filipino G2P.

The expected pronunciations here are the point of the file: they are the
claims the rules are making about Filipino phonology, written down so they
can be argued with. Anything a Filipino speaker disagrees with is a bug in
the rules, not in the test.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tagalog_g2p import (  # noqa: E402
    pronounce, G2PError, PHONES, AMBIGUOUS_GRAPHEMES,
)

failures = []


def check(word, expected, variants=False):
    try:
        got = pronounce(word, variants=variants)
    except G2PError as exc:
        failures.append("%s: raised %s" % (word, exc))
        print("  [FAIL] %-14s raised %s" % (word, exc))
        return
    got_strs = [" ".join(p) for p in got]
    if variants:
        ok = expected in got_strs
        detail = "%r not among %s" % (expected, got_strs)
    else:
        ok = got_strs == [expected]
        detail = "got %s" % got_strs
    if ok:
        # In variant mode show the reading that matched, not just the first,
        # or the output looks like it checked the same thing twice.
        print("  [PASS] %-14s %s" % (word, expected if variants else got_strs[0]))
    else:
        failures.append("%s: %s" % (word, detail))
        print("  [FAIL] %-14s %s" % (word, detail))


def check_raises(word):
    try:
        pronounce(word)
    except G2PError:
        print("  [PASS] %-14s rejected as expected" % word)
        return
    failures.append("%s: should have been rejected" % word)
    print("  [FAIL] %-14s should have been rejected" % word)


print("\nbasic CV words")
check("bata", "B A T A")
check("pusa", "P U S A")
check("guro", "G U R O")
check("mesa", "M E S A")

print("\nword-initial vowels take a glottal onset")
check("aso", "Q A S O")
check("isa", "Q I S A")
check("ulo", "Q U L O")
check("aklat", "Q A K L A T")

print("\nvowel sequences are separate syllables, split by a glottal stop")
check("maaari", "M A Q A Q A R I")
check("oo", "Q O Q O")
check("mais", "M A Q I S")
check("paaralan", "P A Q A R A L A N")

print("\nthe ng digraph")
check("ngipin", "NG I P I N")
check("bahay", "B A H A Y")
# n-g-g: the digraph plus a separate G, not a single NG.
check("sanggol", "S A NG G O L")
# The prefix pang- keeps its NG before a consonant.
check("pangkat", "P A NG K A T")
check("bituing", "B I T U Q I NG")

print("\nhyphen marks a glottal stop before a vowel")
check("pag-asa", "P A G Q A S A")
check("mag-aral", "M A G Q A R A L")

print("\nglides are written, so diphthongs fall out for free")
check("kuwento", "K U W E N T O")
check("silya", "S I L Y A")
check("araw", "Q A R A W")
check("baboy", "B A B O Y")

print("\nSpanish and English loans")
check("tsinelas", "CH I N E L A S")
check("kotse", "K O CH E")           # from Spanish "coche"; ts is the affricate
check("jose", "H O S E")             # Spanish j
check("quezon", "K E S O N")         # qu -> K, and z reads as S in Filipino
check("nino", "N I N O")
check("niño", "N I N Y O")

print("\nreal Phil-IRI / CRLA passage vocabulary")
check("bakuran", "B A K U R A N")
check("naglalaro", "N A G L A L A R O")
check("eskwelahan", "Q E S K W E L A H A N")
check("magsasaka", "M A G S A S A K A")
check("pamilya", "P A M I L Y A")
check("masayang", "M A S A Y A NG")

print("\nwhole-word exceptions")
check("mga", "M A NG A")             # spelled mga, said manga
check("ng", "N A NG")                # the linker

print("\nvariant mode: unwritten final glottal stop")
# "bata" is spelled the same whether or not it ends in a glottal stop, so
# both readings must be offered.
check("bata", "B A T A", variants=True)
check("bata", "B A T A Q", variants=True)

print("\nvariant mode: loan phones and their nativised forms")
check("vaso", "V A S O", variants=True)
check("vaso", "B A S O", variants=True)
check("filipino", "F I L I P I N O", variants=True)
check("filipino", "P I L I P I N O", variants=True)
check("quezon", "K E Z O N", variants=True)   # the marginal /z/ reading
check("jose", "JH O S E", variants=True)      # English-derived j

print("\ninput that must be rejected rather than guessed at")
check_raises("2026")
check_raises("bata2")
check_raises("")
check_raises("hello!")

print("\ninternal consistency")
for word in ["bata", "maaari", "eskwelahan", "tsinelas", "pag-asa", "mga"]:
    for prons in pronounce(word, variants=True):
        unknown = [p for p in prons if p not in PHONES]
        if unknown:
            failures.append("%s: emitted phones outside the inventory: %s"
                            % (word, unknown))
            print("  [FAIL] %-14s unknown phones %s" % (word, unknown))
            break
    else:
        print("  [PASS] %-14s all phones in inventory" % word)

for letter, (default, alts) in AMBIGUOUS_GRAPHEMES.items():
    for option in [default] + alts:
        for phone in option:
            if phone not in PHONES:
                failures.append("ambiguity table for %r references %r, which "
                                "is not in the phone inventory"
                                % (letter, phone))

print()
if failures:
    print("FAILED (%d)" % len(failures))
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("ALL PASS")
