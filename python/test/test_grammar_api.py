#!/usr/bin/env python3
#
# Regression tests for the grammar capability API.
#
# These cover the ways passage-constrained decoding can be absent without the
# caller noticing, which is what an oral reading assessment cannot tolerate:
# a model that cannot take a grammar at all, and passage words the model does
# not know. Both used to be reported only as a warning on stderr.
#
# Needs two models with different graph types:
#
#   test_grammar_api.py <lookahead-model> [hclg-only-model]
#
#   lookahead-model   ships HCLr.fst + Gr.fst, e.g. vosk-model-small-en-us-0.15
#   hclg-only-model   ships a precompiled HCLG.fst, e.g. vosk-model-tl-ph-generic-0.6
#                     optional; the refusal cases are skipped without it
#
# The audio is this repo's python/example/test.wav.

import json
import os
import sys
import wave

from vosk import Model, KaldiRecognizer, SetLogLevel

# Deliberately silenced: these tests assert the API reports failure by itself,
# not that something shows up in a log.
SetLogLevel(-1)

WAV = os.path.join(os.path.dirname(__file__), "..", "example", "test.wav")
PASSAGE = "one zero zero zero one nine oh two one oh zero one eight zero three"

failures = []


def check(name, got, want):
    if got == want:
        print("  [PASS] %s" % name)
    else:
        print("  [FAIL] %s: got %r, want %r" % (name, got, want))
        failures.append(name)


def decode(rec):
    with wave.open(WAV, "rb") as wf:
        while True:
            data = wf.readframes(4000)
            if len(data) == 0:
                break
            rec.AcceptWaveform(data)
    return json.loads(rec.FinalResult())


def test_lookahead_model(path):
    print("\nlookahead model: grammars work")
    model = Model(path)
    check("SupportsRuntimeGrammar", model.SupportsRuntimeGrammar(), True)

    rec = KaldiRecognizer(model, 16000, json.dumps([PASSAGE, "[unk]"]))
    check("constructor grammar decodes the passage", decode(rec)["text"], PASSAGE)
    check("nothing dropped", rec.GrammarMissingWords(), [])

    rec = KaldiRecognizer(model, 16000)
    check("SetGrammar succeeds", rec.SetGrammar(json.dumps([PASSAGE, "[unk]"])), True)
    check("SetGrammar decodes the passage", decode(rec)["text"], PASSAGE)

    # Off-passage speech has to surface as [unk]; that is the miscue signal.
    rec = KaldiRecognizer(model, 16000, json.dumps(["one zero zero zero one", "[unk]"]))
    check("off-passage speech becomes [unk]", decode(rec)["text"],
          "one zero zero zero one [unk] zero one [unk]")

    print("\nlookahead model: dropped passage words are reported")
    # Words the model does not know are dropped from the grammar and can never
    # be matched, so a reader who says one correctly is scored as saying
    # something else. Note you cannot guess which words a model knows, which is
    # what FindWord is for.
    words = ["bakuran", "naglalaro"]
    for word in words:
        check("%r really is out of vocabulary" % word, model.FindWord(word), -1)
    rec = KaldiRecognizer(model, 16000, json.dumps(["one zero " + " ".join(words), "[unk]"]))
    check("dropped words reported", sorted(rec.GrammarMissingWords()), sorted(words))

    rec = KaldiRecognizer(model, 16000)
    rec.SetGrammar(json.dumps(["one zero " + words[0], "[unk]"]))
    check("dropped words reported via SetGrammar", rec.GrammarMissingWords(), [words[0]])
    rec.SetGrammar("[]")
    check("cleared when the grammar is reset", rec.GrammarMissingWords(), [])

    print("\nlookahead model: a bad grammar is rejected, not half-applied")
    rec = KaldiRecognizer(model, 16000)
    check("malformed grammar rejected", rec.SetGrammar('"not an array"'), False)
    # The old code freed the decoding graph before building the replacement, so
    # a rejected grammar left the recognizer holding freed memory.
    check("recognizer still usable after a rejected grammar", decode(rec)["text"] != "", True)


def test_hclg_only_model(path):
    print("\nHCLG-only model: grammars are refused, not silently ignored")
    model = Model(path)
    check("SupportsRuntimeGrammar", model.SupportsRuntimeGrammar(), False)

    try:
        KaldiRecognizer(model, 16000, json.dumps(["one zero", "[unk]"]))
        check("constructor refuses the grammar", "no exception", "an exception")
    except Exception:
        check("constructor refuses the grammar", True, True)

    rec = KaldiRecognizer(model, 16000)
    check("SetGrammar reports failure", rec.SetGrammar(json.dumps(["one zero", "[unk]"])), False)


if len(sys.argv) < 2:
    print(__doc__)
    print("Usage: test_grammar_api.py <lookahead-model> [hclg-only-model]")
    sys.exit(1)

test_lookahead_model(sys.argv[1])
if len(sys.argv) > 2:
    test_hclg_only_model(sys.argv[2])
else:
    print("\nSkipping HCLG-only checks, no second model given")

print("\n%s" % ("ALL PASS" if not failures else "FAILED: " + ", ".join(failures)))
sys.exit(1 if failures else 0)
