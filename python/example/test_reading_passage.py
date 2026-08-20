#!/usr/bin/env python3
#
# Passage-constrained decoding, the way an oral reading assessment needs it.
#
# The point of constraining the decoder to a reference passage is that words
# the reader did not say cannot be invented, and words outside the passage come
# back as [unk]. Two things silently break that, and this example checks both
# before decoding anything:
#
#   1. Models that ship a precompiled HCLG.fst cannot take a runtime grammar.
#      Older versions of vosk accepted the grammar anyway and free-decoded, so
#      the output looked fine and meant nothing.
#
#   2. Passage words missing from the model vocabulary are dropped from the
#      grammar. The decoder can then never match them, so a reader who says a
#      dropped word correctly is scored as having said something else.
#
# Usage: test_reading_passage.py <model-path> <audio.wav>

import json
import sys
import wave

from vosk import Model, KaldiRecognizer, SetLogLevel

SetLogLevel(-1)

PASSAGE = "one zero zero zero one nine oh two one oh zero one eight zero three"

if len(sys.argv) != 3:
    print(__doc__)
    print("Usage: test_reading_passage.py <model-path> <audio.wav>")
    sys.exit(1)

model = Model(sys.argv[1])

# 1. Can this model be constrained at all?
if not model.SupportsRuntimeGrammar():
    print("This model has no HCLr.fst/Gr.fst pair, so it cannot be constrained "
          "to a passage. Scoring against it would measure free decoding, not "
          "reading. Use a model built with a lookahead graph.")
    sys.exit(1)

# 2. Which passage words does the model not know?
unknown = [w for w in PASSAGE.split() if model.FindWord(w) < 0]
if unknown:
    print("Not in the model vocabulary, will be dropped:", " ".join(unknown))

# "[unk]" is what makes off-passage speech detectable. Without it the decoder
# must emit some passage word for whatever it hears, and a reader who cannot
# read the passage at all still produces a plausible-looking result.
grammar = json.dumps([PASSAGE, "[unk]"])

wf = wave.open(sys.argv[2], "rb")
if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getcomptype() != "NONE":
    print("Audio file must be WAV format mono PCM.")
    sys.exit(1)

rec = KaldiRecognizer(model, wf.getframerate())
if not rec.SetGrammar(grammar):
    print("Failed to apply the passage grammar.")
    sys.exit(1)
rec.SetWords(True)

# 3. Report anything the grammar builder dropped, for the same reason as (2).
# This catches tokens FindWord cannot, such as punctuation left on a word.
dropped = rec.GrammarMissingWords()
if dropped:
    print("Dropped from the grammar:", " ".join(dropped))

while True:
    data = wf.readframes(4000)
    if len(data) == 0:
        break
    rec.AcceptWaveform(data)

result = json.loads(rec.FinalResult())
words = result.get("result", [])

print("\nheard:", result.get("text", ""))
print("\n%-12s %8s %8s" % ("word", "start", "end"))
for w in words:
    print("%-12s %8.2f %8.2f" % (w["word"], w["start"], w["end"]))

# Word confidences saturate at 1.0 once the search space is this small, so they
# are not a miscue signal. What carries information is where [unk] appears and
# how the timings line up against the reference.
spoken = [w["word"] for w in words]
matched = sum(1 for w in spoken if w != "[unk]")
print("\n%d/%d decoded tokens matched the passage, %d were off-passage ([unk])"
      % (matched, len(spoken), len(spoken) - matched))
