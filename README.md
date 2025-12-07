# Wiktionary Parser

[![CI](https://github.com/immersive-flashcards/wiktionary-parser/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/immersive-flashcards/wiktionary-parser/actions/workflows/ci.yml)

This repository extracts **infinitive verbs** and **full conjugation data** from Kaikki/Wiktionary JSONL dumps for use in the _Dynamic Verb Conjugation_ project.

- **Infinitive extraction:** filters raw entries by language rules.
- **CSV generation:** normalizes tense/person tags, reflexives, pronouns, and metadata into per-verb CSV files.

See the main conjugation project here: [`Dynamic Verb Conjugation`](https://github.com/DonCiervo/dynamic-verb-conjugation)

---

## 📜 Licensing Terms

1. All **source code** in this repository is licensed under the **MIT License**
(see [`LICENSE`](./LICENSE)).

2. All **Wiktionary-derived data** including the **Kaikki dumps** are licensed under **CC BY-SA 4.0**.
   (see [`DATA_LICENSE`](./data/DATA_LICENSE)).
