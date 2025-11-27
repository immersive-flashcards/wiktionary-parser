# How to use

This project converts Kaikki or Wiktionary JSONL dumps into per verb CSV conjugation tables.

## 1. Extract infinitive verbs

1. Place your Kaikki dump at  
   `data/language-dumps/<lang>-extract.jsonl`
2. Run:

   ```bash
   python extract_infinitives.py
    ```
3. The script generates `data/language-dumps/<lang>-infinitives.jsonl` based on the configuration.

## 2. Generate per-verb CSV conjugation tables

1. Ensure ''data/language-verb-dumps/<lang>-infinitives.jsonl'' exists.

2. Run:

   ```bash
   python generate_verb_csvs.py
   ```
   
3. The script generates per-verb CSV files in `data/verb-csvs/<lang>/`.

