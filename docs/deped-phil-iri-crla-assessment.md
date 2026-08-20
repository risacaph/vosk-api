# Vosk for DepEd Phil-IRI and CRLA — Fork Assessment

**Repository:** `risacaph/vosk-api` (fork of `alphacephei/vosk-api`)
**Base commit assessed:** `05adbfc` — *Fix typo in doc comment (#2059)*
**Date:** 2026-08-20

---

## 0. Verdict in one paragraph

Vosk is the right *engine* choice for Phil-IRI and CRLA — it is offline, Apache-2.0,
runs on Android, and already emits the word-level timings and passage-constrained
decoding that oral reading assessment depends on. It is **not** usable for Filipino
oral reading today, and the reason is the **model, not the code**: the only Filipino
model published for Vosk (`vosk-model-tl-ph-generic-0.6`) ships a pre-compiled
`HCLG.fst`, which means passage-constrained decoding is *silently unavailable*, it
has no `[unk]` garbage symbol, and it needs ~864 MB RAM to load. Every one of those
is fatal for a Phil-IRI use case on a DepEd tablet. The engine-side work in this fork
is real but modest; the expensive, unavoidable work is producing a small Filipino
(and eventually mother-tongue) acoustic model with a lookahead graph and child speech
in the training data.

---

## 1. State of this fork

This fork is **byte-identical to upstream**. There is no DepEd-specific work in it yet.

```
$ git log --oneline -1 master
05adbfc Fix typo in doc comment (#2059)
$ git log --oneline master..HEAD      # no divergence
```

* **License:** Apache 2.0 (`COPYING`) — compatible with government deployment and
  with distributing a modified build to schools. No copyleft obligation on the app
  that links `libvosk`.
* **Bindings present:** C, Python, Java, **Android**, Kotlin, Node.js, C#, Go, Rust, Ruby, WebJS.
* **Model of interest:** `vosk-model-tl-ph-generic-0.6` is third-party
  (F. Ang / `feddybear/flipside_ph`), Apache-2.0, trained on the Filipino Speech Corpus
  (UP Diliman), ISIP Tagalog Corpus, CSL Tagalog (KIT/CMU), ICE-Philippines text and
  Babel Tagalog texts — **all adult speech**.

The strategic argument for Vosk is worth stating explicitly, because it drives
everything else: Phil-IRI and CRLA record **children's voices**. Keeping recognition
fully on-device means child voice data never leaves the classroom, which is the
cleanest posture under RA 10173 (Data Privacy Act) and DepEd's own data-sharing
rules. A cloud ASR would be cheaper to get working and much harder to defend.

---

## 2. What the two assessments actually need from ASR

| Assessment measure | ASR capability required | Vosk status |
|---|---|---|
| Phil-IRI oral reading: word reading score | Passage-constrained decode + reliable OOV/garbage detection | Engine: **yes**. Filipino model: **no** |
| Phil-IRI reading rate / WCPM | Word-level start/end timestamps | **Yes**, verified |
| Phil-IRI miscue: omission, insertion, substitution | Alignment of hypothesis to reference passage | Engine gives the substrate; alignment layer must be built |
| Phil-IRI miscue: repetition, reversal/transposition | Decoder must permit *and mark* re-reads and re-ordering | **Partial** — current grammar is an unordered bigram (§4.4) |
| Phil-IRI miscue: mispronunciation vs. substitution | Phone-level alignment / pronunciation scoring | **No** — not exposed by the API (§4.5) |
| Phil-IRI comprehension questions | Not ASR (teacher-scored or item-based) | N/A |
| CRLA word reading (isolated familiar/unfamiliar words) | Small-grammar decode per item + garbage model | Engine: yes. Filipino model: no |
| CRLA letter name knowledge | Small-grammar decode per item | Engine: yes |
| CRLA **letter sound** knowledge | Phoneme-level scoring (GOP) | **No** (§4.5) |
| CRLA in Mother Tongue (G1–G3 MTB-MLE) | Acoustic + language model per MT language | **None exist** (§4.7) |

> Cut scores, miscue taxonomy details and the Independent / Instructional / Frustration
> banding must be taken from the current DepEd issuances (Phil-IRI Manual and the
> governing CRLA memorandum), not hard-coded from this document.

---

## 3. What the engine gives us today (measured, not assumed)

All numbers below were measured on this checkout using the published wheels and
models, on a 4-core x86 container.

**Word timings and confidence** — `SetWords(True)` yields per-word `start`, `end`, `conf`:

```json
{"conf": 1.0, "start": 0.84, "end": 1.11, "word": "one"}
```

That is everything needed for reading rate, inter-word pause detection and hesitation
timing.

**Passage-constrained decoding works, and it matters.** On `vosk-model-small-en-us-0.15`
with `python/example/test.wav`:

| Mode | Output |
|---|---|
| Free decode | `one zero zero zero one nine oh two **i no** zero one eight zero three` |
| Grammar = passage + `[unk]` | `one zero zero zero one nine oh two **one oh** zero one eight zero three` |

Constraining the decoder to the passage fixed a substitution error outright. For
reading assessment this is not an optimisation, it is the mechanism.

**`[unk]` is the miscue signal.** Giving the recogniser only *part* of the passage:

```
grammar = ["one zero zero zero one", "[unk]"]
result  = one zero zero zero one [unk] zero one [unk]
```

Words outside the passage collapse to `[unk]`. Passage words that survive were read;
`[unk]` spans are where the child departed from the text. This is the substrate a
miscue scorer is built on.

**Performance is not the constraint.**

| Model | RTF | Peak RSS | Load time |
|---|---|---|---|
| `vosk-model-small-en-us-0.15` | 0.17 | 188 MB | 1.1 s |
| `vosk-model-tl-ph-generic-0.6` | 0.16 | **864 MB** | 5.9 s |

CPU is fine even on modest hardware. **Memory is the problem**, and only for Filipino.

---

## 4. Verified blockers

### 4.1 The Filipino model cannot do passage-constrained decoding — and fails silently

`vosk-model-tl-ph-generic-0.6` ships `graph/HCLG.fst` (701 MB) and **no `HCLr.fst` /
`Gr.fst`**. Runtime grammars require the lookahead pair. Measured:

```
>>> KaldiRecognizer(model, 16000, '["ang mga bata ay masayang naglalaro", "[unk]"]')
WARNING (VoskAPI:Recognizer():recognizer.cc:59) Runtime graphs are not supported by this model
>>> rec.SetGrammar(...)
WARNING (VoskAPI:SetGrm():recognizer.cc:240) Runtime graphs are not supported by this model
```

Compare the model layouts:

| | `small-en-us-0.15` | `tl-ph-generic-0.6` |
|---|---|---|
| `HCLr.fst` + `Gr.fst` | ✅ 22 MB + 24 MB | ❌ absent |
| `HCLG.fst` | — | 701 MB |
| Runtime grammar | supported | **unsupported** |

The dangerous part is what happens next. In `src/recognizer.cc`:

```cpp
if (model_->hcl_fst_) {
    UpdateGrammarFst(grammar);
} else {
    KALDI_WARN << "Runtime graphs are not supported by this model";
}
decoder_ = new kaldi::SingleUtteranceNnet3IncrementalDecoder(...,
        model_->hclg_fst_ ? *model_->hclg_fst_ : *decode_fst_, ...);
```

The constructor **succeeds** and quietly falls back to full free decoding. The only
signal is a Kaldi warning — and every example in this repo, including
`python/example/test_srt.py`, calls `SetLogLevel(-1)` first. An app team would ship a
"passage-constrained" reading assessor that is in fact free-decoding, and nothing in
the API would tell them.

### 4.2 The Filipino model has no `[unk]`, so it cannot reject off-passage speech

```
find_word('bata')  = 17746
find_word('[unk]') = -1        # absent
find_word('<unk>') = 1759      # LM unk symbol, not a phone-loop garbage word
```

Without `[unk]`, a constrained decoder is forced to emit *some* passage word for
whatever it hears. Demonstrated on English, with a grammar that deliberately did not
match the audio:

| Grammar | Output |
|---|---|
| wrong passage **+ `[unk]`** | `[unk] [unk] [unk]` ← correct behaviour |
| wrong passage, **no `[unk]`** | `jumps over over the over over dog jumps over the over lazy over the` |

That second row is the failure mode that would invalidate the whole instrument: a
child who cannot read the passage at all still produces a fluent-looking word
sequence drawn from the passage vocabulary, and scores well. **Any Filipino model we
adopt must include a garbage/phone-loop `[unk]`.** This is non-negotiable.

### 4.3 864 MB is not deployable on DepEd hardware

776 MB on disk, 864 MB resident. On the 2 GB-RAM Android tablets typical of DepEd
deployments, the Android runtime will not give a single app that allocation. The
English small model does the same job in 188 MB. Target: **a Filipino model in the
50–80 MB class**, which is exactly what a `small`-type lookahead build produces.

### 4.4 The grammar builder is a bigram, not a reading tracker

`Recognizer::UpdateGrammarFst()` estimates an n-gram LM over the phrase list:

```cpp
opts.ngram_order = 2;
opts.discount = 0.5;
```

A bigram with backoff does not enforce passage order. Measured, with the passage as
the only grammar entry:

```
jumps over over the over over dog jumps over the over lazy over the
```

The decoder freely reordered and repeated. For Phil-IRI that is wrong in both
directions: it will not flag a transposition (a scoreable miscue), and it invites
spurious repetitions. What reading assessment needs is a **linear passage FST** —
states following the reference text in order, with explicit, individually-weighted
arcs for *skip* (omission), *back-jump* (repetition / regression), *self-loop through
garbage* (insertion, mispronunciation) and *early termination*. Then the decoded path
through that FST **is** the miscue record, rather than something a downstream aligner
has to guess at.

### 4.5 No phone-level output — two consequences

The C API exposes words, times, MBR confidences, n-best and NLSML. It exposes no
phone alignment and no pronunciation scoring, even though the underlying lattice and
`word_boundary.int` carry the information (`WordAlignLattice` is already called in
`recognizer.cc`).

1. **Phil-IRI cannot distinguish "mispronunciation" from "substitution."** Both surface
   as `[unk]` or a wrong word. These are separate categories in the miscue taxonomy.
2. **CRLA letter-sound knowledge cannot be scored at all.** Scoring whether a child
   produced /b/ correctly is a phoneme-level judgement (a goodness-of-pronunciation
   measure), not a word-level one.

### 4.6 Word confidence is not a usable miscue signal in grammar mode

Across every grammar-constrained run measured, `conf` was `1.0` — including on
`[unk]` tokens. MBR confidence saturates once the search space is small. Separately,
the `confidence` field on n-best alternatives is an unnormalised likelihood
(observed: `707.2`), not a probability.

**Implication for the scoring layer:** do not threshold on `conf`. The reliable
signals are (a) `[unk]` occurrence, (b) alignment against the reference passage, and
(c) timing — pause length before a word, and per-word duration.

### 4.7 No mother-tongue models exist

Vosk publishes 131 models across 36 language tags. Exactly one is Philippine:
`tl-ph`. CRLA is administered in the mother tongue in the early grades, and MTB-MLE
covers 19+ languages (Cebuano, Ilocano, Hiligaynon, Waray, Bikol, Kapampangan,
Pangasinan, Tausug, Maguindanaon, Maranao, Chavacano, and others). **There is no
model for any of them.**

One nuance worth recording, since it changes the cost estimate: the `tl-ph`
vocabulary is 236,529 entries and, being drawn from broad text corpora, it already
*contains* much of the shared Austronesian lexicon. Sampled coverage:

| Word list | OOV rate |
|---|---|
| Filipino Phil-IRI-style passage words | 0% |
| Filipino school/assessment terms | 0% |
| Common learner names | 0% |
| CRLA-type early-grade words | 0% |
| Cebuano sample | 0% |
| Hiligaynon sample | 0% |
| Ilocano sample | 31% |

Lexical coverage is *not* the bottleneck for Tagalog, and is better than expected for
Cebuano/Hiligaynon. But vocabulary presence is not recognition: the acoustic model and
LM are Tagalog-weighted, so decoding Cebuano speech with this model will still perform
badly. It does mean an MT effort can lean on lexicon reuse and focus its budget on
acoustic data.

### 4.8 The Filipino model has no children in its training data

Every corpus behind `tl-ph-generic-0.6` is adult speech. Child ASR error rates run
substantially higher than adult rates on adult-trained models — children have shorter
vocal tracts, higher and more variable pitch, slower and more disfluent delivery, and
*beginning readers in particular* produce sounded-out, elongated, restarted words that
adult models have never seen. This is a **measurement-validity** risk, not just an
accuracy one: if error rates differ systematically by grade level or by L1 background,
the instrument scores different children on different scales.

### 4.9 Binding gaps that matter for the Android build

`vosk_model_find_word()` — the natural way to check, on-device, whether a passage word
is even in the model's vocabulary before constraining to it — is wrapped in Python, Go
and Ruby, but **not in the Java, Android or Node.js bindings**. Android is precisely
where a DepEd app would need it.

(Endpointer controls, by contrast, *are* exposed in both the Java and Python bindings
in this checkout — `setEndpointerMode` / `setEndpointerDelays`. Those need
configuration for child readers, not new code; see §5.A6.)

### 4.10 Out-of-vocabulary passage words are dropped silently

```cpp
int32 id = model_->word_syms_->Find(token);
if (id == kNoSymbol) {
    KALDI_WARN << "Ignoring word missing in vocabulary: '" << token << "'";
}
```

A passage word that is not in `words.txt` — a local place name, a pupil's name, an MT
loanword — is dropped from the grammar with only a suppressed warning. The passage
FST then cannot match it, so a child who reads it *correctly* is scored as having
produced garbage. The caller gets no indication this happened.

---

## 5. What we can improve

Ranked by (value to the assessments) ÷ (cost), and separated by who has to do the work.

### Tier A — changes in this fork (small team, weeks)

**A1. Passage / reading-tracker FST API.** *The highest-value change in this repo.*
Add an entry point alongside `vosk_recognizer_set_grm`:

```c
void vosk_recognizer_set_passage(VoskRecognizer *recognizer,
                                 const char *reference_text,
                                 const char *options_json);
```

Build a linear FST over the reference tokens with explicitly weighted skip,
back-jump, garbage-self-loop and early-exit arcs, instead of routing through
`LanguageModelEstimator`'s bigram. Emit, per reference token, whether it was matched,
skipped, repeated or substituted. This turns miscue detection from a downstream
guess into a decoder output. It also fixes §4.4.

**A2. Make "grammar unsupported" impossible to miss.** Add
`int vosk_model_supports_runtime_grammar(VoskModel *model);` and have the grammar
constructor and `SetGrm` report failure through a return code rather than a warning
that `SetLogLevel(-1)` erases. Small patch; prevents an entire class of silently
invalid deployment (§4.1).

**A3. Report dropped OOV passage words to the caller.** Return the list of tokens
that were not found in `words.txt` so the app can warn the teacher, or fall back to
a phonetic spelling, instead of silently mis-scoring (§4.10).

**A4. Expose phone-level alignment and a pronunciation score.** Add
`vosk_recognizer_set_phones(recognizer, 1)` emitting phone segments with times, and a
per-word goodness-of-pronunciation value. The lattice and `word_boundary.int` already
carry what is needed. Unlocks mispronunciation-vs-substitution for Phil-IRI and letter-
sound scoring for CRLA (§4.5). Highest engineering effort in Tier A; sequence it after A1.

**A5. Binding parity for Android.** Wrap `vosk_model_find_word` in the Java, Android
and Node.js bindings (§4.9). Trivial, and needed by any real on-device passage check.

**A6. A child-oral-reading endpointer profile.** Beginning readers pause for seconds
mid-passage. Default endpointing will cut utterances at exactly the wrong moments.
No new code — establish and document a tested configuration
(`setEndpointerDelays` with a long `t_end`, or endpointing suppressed entirely for
passage reading with app-controlled segmentation) and ship it as a preset.

### Tier B — model work (this is the real cost, and the real blocker)

**B1. A small Filipino lookahead model with `[unk]`.** Rebuild `tl-ph` as a
`small`-type model: `HCLr.fst` + `Gr.fst` instead of a monolithic `HCLG.fst`, a
pruned and cleaned lexicon (the current 236 k vocabulary contains junk tokens like
`''hawaiian`, `'5.`), and a phone-loop `[unk]`. Target 50–80 MB and <200 MB RSS.
**Without B1, nothing else in this document can ship for Filipino.** The `training/`
directory in this repo carries a Kaldi TDNN-chain recipe that is a reasonable
starting point.

**B2. A Filipino child oral-reading corpus.** The single highest-value data asset,
and the one only DepEd can realistically create. Even a few dozen hours of Grade 1–6
children reading Phil-IRI/CRLA-style passages, transcribed with miscues marked,
would (a) allow acoustic fine-tuning, (b) give a real validation set against
teacher-scored ground truth, and (c) let us report per-grade error rates — which is
what makes the instrument defensible. Consent, retention and de-identification need
to be designed in from the start, not retrofitted.

**B3. Mother-tongue models.** Per-language acoustic data is unavoidable, but §4.7
shows lexicon reuse can cut the cost. Sequence by MTB-MLE enrolment: Cebuano,
Ilocano, Hiligaynon first. This is a multi-year programme, not a sprint — plan CRLA
MT support accordingly and be explicit with stakeholders that it will not arrive with
the Filipino release.

### Tier C — the scoring layer (belongs in the app, not in this repo)

Reference-passage alignment → miscue typing → word reading score → WCPM → Phil-IRI
banding. Deliberately keep this **out** of `libvosk`: the rubric and cut scores change
by DepEd issuance, and they must be updatable without shipping a new native binary.
Build it against the §4.6 finding — align and use timing, do not threshold on `conf`.

---

## 6. Suggested sequencing

| Phase | Work | Gate |
|---|---|---|
| 0 | A2, A3, A5 — make failures visible | No behaviour change; safe to merge first |
| 1 | **B1** — small Filipino lookahead model with `[unk]` | Grammar decode demonstrably works in Filipino |
| 2 | A1 — passage tracker FST; Tier C scoring layer | Miscue output validated against teacher scoring |
| 3 | B2 — child corpus; acoustic fine-tune; A6 tuning | Per-grade error rates measured and published |
| 4 | A4 — phone-level / GOP | CRLA letter-sound + mispronunciation typing |
| 5 | B3 — mother-tongue models | Per language, as data allows |

Phases 0 and 1 are independent and can run in parallel — but **Phase 1 gates
everything else for Filipino.**

---

## 7. Risks to name early

* **Measurement validity.** An ASR-scored instrument is only defensible if its error
  rate is known and roughly uniform across the children being compared. Budget for a
  validation study against teacher scoring, reported per grade and per L1 background,
  before any high-stakes use.
* **Silent degradation.** §4.1 and §4.10 are both cases where the system produces
  plausible output while doing the wrong thing. Fix these before pilot, not after.
* **Scope discipline on mother tongue.** MT support is the part stakeholders will
  assume is included. It is the most expensive part and the furthest out. Say so early.
* **Child voice data.** On-device recognition is the reason this architecture is
  defensible under RA 10173. Any drift toward cloud recognition or centralised audio
  retention changes the privacy analysis completely.

---

## 8. Recommendation

Keep Vosk. Do not fork away from upstream more than necessary — Tier A is a small,
clean set of additions that can stay rebase-able on upstream, and A2/A3/A5 are
arguably upstreamable as-is.

Start Phase 0 and Phase 1 now. Treat **B1 (a small Filipino lookahead model with an
`[unk]` phone loop)** as the project's critical path, because it is: no amount of
engine work in this repository produces a working Filipino reading assessor without
it. And begin the conversation about **B2 (child speech data)** immediately, because
it has the longest lead time of anything here and it is the one input no vendor can
supply on DepEd's behalf.

---

## Appendix — reproducing the measurements

```bash
pip install vosk
curl -O https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
curl -O https://alphacephei.com/vosk/models/vosk-model-tl-ph-generic-0.6.zip
unzip -q vosk-model-small-en-us-0.15.zip && unzip -q vosk-model-tl-ph-generic-0.6.zip

# §4.1 — grammar support by model layout
ls vosk-model-small-en-us-0.15/graph/    # HCLr.fst  Gr.fst  -> grammars supported
ls vosk-model-tl-ph-generic-0.6/graph/   # HCLG.fst        -> grammars unsupported

# §4.1/§4.2 — keep Kaldi logging ON, or the warnings are invisible
python3 - <<'PY'
import json
from vosk import Model, KaldiRecognizer, SetLogLevel
SetLogLevel(0)
m = Model("vosk-model-tl-ph-generic-0.6")
print("[unk] ->", m.vosk_model_find_word("[unk]"))          # -1
KaldiRecognizer(m, 16000, json.dumps(["ang mga bata", "[unk]"]))
PY

# §3/§4.2/§4.4 — grammar behaviour, using this repo's test.wav
#   grammar ["one zero zero zero one", "[unk]"]      -> one zero zero zero one [unk] zero one [unk]
#   grammar ["the quick brown fox ...", "[unk]"]     -> [unk] [unk] [unk]
#   grammar ["the quick brown fox ..."]  (no [unk])  -> jumps over over the over over dog ...
```
