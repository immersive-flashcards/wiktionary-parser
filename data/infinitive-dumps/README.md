# Kaikki Infinitive Dumps

This directory contains the actively used [Kaikki](https://kaikki.org/) exports, filtered down to only the Wiktionary articles for the infinitive forms of verbs.

## Naming

The files follow the pattern of ´ab-cd-infinitives.jsonl.zst`, where
 - `ab` is the language of the verbs
 - `cd` is the language of the wiktionary version the data was taken from

For instance, `ca-en-infinitives.jsonl.zst` contains Catalan infinitive verbs from the English Wiktionary, 
since `ca-ca` wasn't available on Kaikki.

## Generation and File Format

The dumps are generated in `src/kaikki_handlers/extract_infinitives.py` and compressed using `zstd`. 
The files are in `JSON Lines` format, where each line is a `JSON` object representing a verb entry.