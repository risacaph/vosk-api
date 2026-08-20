# Filipino (Tagalog) grapheme-to-phoneme

Rule-based G2P that turns Filipino spelling into a pronunciation lexicon, and
writes a Kaldi dict directory directly.

## Why this is here

Passage-constrained decoding is what an oral reading assessment runs on, and it
needs a model with a lookahead graph (`HCLr.fst` + `Gr.fst`) and an `[unk]`
phone loop. The only published Filipino Vosk model,
`vosk-model-tl-ph-generic-0.6`, has neither — see
[`docs/deped-phil-iri-crla-assessment.md`](../../docs/deped-phil-iri-crla-assessment.md).

Rebuilding it needs a lexicon. The original came from
`data/raw/KIT_TGL/TEXT_DATA/kaldi_lexicon`, part of the licensed KIT/CMU
Tagalog corpus, so it cannot be redistributed. Filipino orthography is close to
phonemic, which makes generating one by rule practical — unlike English, where
you would need a trained G2P.

## Usage

```bash
./tagalog_g2p.py bata mga pag-asa       # pronounce words
./tagalog_g2p.py --variants bata        # every reading spelling leaves open
echo "aso pusa" | ./tagalog_g2p.py -    # from stdin
./tagalog_g2p.py --phones               # print the phone inventory

# Write a Kaldi dict directory, the same files local/prepare_dict.sh produces
./tagalog_g2p.py --dict-dir data/local/dict --wordlist vocab.txt
```

Words that cannot be converted are reported rather than guessed at, and
`--dict-dir` exits non-zero if any failed. That matters here: a wrong
pronunciation in a reading assessment is scored as a child's error.

## Phone set

27 phones, ASCII and uppercase. Native Filipino is the first two rows; the
loan consonants are reachable only through Spanish and English borrowings,
which early-grade passages are full of.

| Class | Phones |
|---|---|
| Vowels | `A E I O U` |
| Native consonants | `P B T D K G Q M N NG S H L R W Y` |
| Loan consonants | `F V Z SH CH JH` |
| Non-speech | `SIL SPN` |

`Q` is the glottal stop and `NG` the velar nasal. There are no stress or tone
markers, so `extra_questions.txt` is empty.

## What the rules cover

Most of Filipino spelling is one letter to one phone. The cases that are not:

| Spelling | Phones | Example |
|---|---|---|
| `ng` digraph | `NG` | ngipin → `NG I P I N` |
| `ng` + `g` | `NG G` | sanggol → `S A NG G O L` |
| word-initial vowel | `Q` inserted | aso → `Q A S O` |
| vowel + vowel | `Q` between | maaari → `M A Q A Q A R I` |
| hyphen before vowel | `Q` | pag-asa → `P A G Q A S A` |
| `ts`, `ch` | `CH` | tsinelas → `CH I N E L A S` |
| `c` before `e`/`i` | `S`, else `K` | — |
| `qu` before `e`/`i` | `K` | Quezon → `K E S O N` |
| `gu` before `e`/`i` | `G` | — |
| `ñ` | `N Y` | niño → `N I N Y O` |
| `ll` | `L Y` | apellido |
| `x` | `K S` | — |

Glides are written in modern Filipino orthography (`kuwento`, `silya`), so
diphthongs need no special handling — `w` and `y` are just `W` and `Y`.

Two whole-word exceptions earn their place: `mga`, the plural marker, is said
*manga*; and the linker `ng` is said *nang*.

## What spelling does not encode

Three things are genuinely not recoverable from Filipino text. `--variants`
emits every legitimate reading rather than picking one, which is the normal way
to handle this for ASR — the decoder takes whichever matches the audio.

- **Word-final glottal stop.** Never written. *batà* (child) and *bata*
  (bathrobe) are both spelled `bata`. Variant mode emits `B A T A` and
  `B A T A Q`.
- **Stress.** Unwritten, and it distinguishes minimal pairs. Not modelled at
  all — the phone set has no stress marks, matching the original recipe.
- **Loan letters.** Speakers vary between the borrowed phone and its nativised
  counterpart: `f`/`p` (*Filipino* ~ *Pilipino*), `v`/`b`, `z`/`s`, and `j` as
  `/h/` (Spanish *Jose*) or `/dʒ/` (English). Defaults are the common Filipino
  reading; variant mode adds the rest.

### Known limitation

The vowel-sequence rule inserts a glottal stop between any two vowels, which is
right for native Filipino but over-applies to loanwords kept in their source
spelling: `video` becomes `V I D E Q O` where a speaker would more likely say
*bid-yo*. In practice Filipino writes such words with the glide (`bidyo`,
`pamilya`) and passages use the Filipino spelling, so this mostly does not
arise. Where it does, add the word to `EXCEPTIONS`.

## Coverage

Checked against the 236,524-entry vocabulary of
`vosk-model-tl-ph-generic-0.6`:

| | |
|---|---|
| Entries converted | 232,924 (98.5%) |
| Restricted to purely alphabetic entries | **232,924 of 232,937 — 99.99%** |
| Rejected | 3,600, all non-alphabetic |

Every rejection is a junk token from the source text corpora (`''hawaiian`,
`'.`, `'5.`) or a run of hyphens — the same lexicon noise flagged in the
assessment. Refusing them is the wanted behaviour: the G2P doubles as a
vocabulary filter.

## Feeding this into a model build

`--dict-dir` writes `lexicon.txt`, `nonsilence_phones.txt`,
`silence_phones.txt`, `optional_silence.txt` and `extra_questions.txt` — the
inputs `utils/prepare_lang.sh` expects.

**The `[unk]` entry in `lexicon.txt` is a placeholder, not a garbage model.**
It maps to a single `SPN` phone, which is exactly what the current `tl-ph`
model does and exactly why that model cannot reject off-passage speech: a
single phone cannot absorb an arbitrary utterance. A passage-constrained
recogniser needs `[unk]` backed by a phone-level loop, built with Kaldi's
`utils/lang/make_unk_lm.sh` after `prepare_lang.sh`. Without that step a child
who cannot read the passage still decodes into passage words and scores well —
demonstrated in §4.2 of the assessment.

The graph then has to be built as a lookahead pair rather than a single
`HCLG.fst`, or `vosk_recognizer_set_grm()` will refuse it. Check with
`vosk_model_supports_runtime_grammar()`.

## Tests

```bash
./test_tagalog_g2p.py
```

The expected pronunciations in that file are the claims these rules make about
Filipino phonology, written down so a speaker can argue with them. If one is
wrong, the rule is wrong — fix `tagalog_g2p.py`, not the test.
