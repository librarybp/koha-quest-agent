# Running the technical evaluation

This produces real results for the paper: the full agent (language model + MCP server + your Koha) answers 24 test cases, 3 times each, and every reply is scored automatically. You then rate the replies by hand.

Koha is only read. Quest data goes to a separate, temporary database.

## 1. Prepare a test patron (5 minutes)

Use a dummy patron, not a real student, so no real student's data is used.

1. In Koha, add a patron: *Test Student*, category = your student category, library = Barpeta Polytechnic.
2. Check out **two books** to this patron (needed for the "my loans" test).
3. Note the patron's **borrowernumber**.

## 2. Fill in the library facts (5 minutes)

- Edit `library_info.json`: replace every "Edit this" with your real hours, loan rules, reading room and reference collection details.
- In `quests.json`, quest `ori-02` expects the loan period **14 days**. If your rule is different, change its `accepted` answers. In `eval/cases.json`, case `QST-5`, change "14 days" to match.

## 3. Choose the language model

Your Lenovo E49 is too slow to run a model, so use one of these:

| Option | `.env` settings |
| --- | --- |
| **Google Gemini API** (free tier, key from aistudio.google.com) | `LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai` `LLM_API_KEY=<your key>` `LLM_MODEL=<a current Gemini Flash model name from the Gemini API docs>` |
| **Groq** (free tier, key from console.groq.com) | `LLM_BASE_URL=https://api.groq.com/openai/v1` `LLM_API_KEY=<your key>` `LLM_MODEL=<a Groq model that supports tool use>` |
| **Ollama on a stronger PC** in the library | `LLM_BASE_URL=http://<that-PC-IP>:11434/v1` `LLM_API_KEY=ollama` `LLM_MODEL=qwen2.5:7b` |

With a hosted service, the test patron's first name and loan due dates are sent to that provider; that is why step 1 uses a dummy patron.

## 4. Install and check (10 minutes)

Unzip the new package over the old folder; your existing `.env` is kept. Then add the model settings from step 3 to `.env`.

```bash
cd ~/Downloads
unzip -o koha-quest-agent.zip && cd koha-quest-agent
nano .env                                # add the LLM_ lines from step 3
venv/bin/pip install -r requirements.txt
venv/bin/python scripts/check_koha.py <test borrowernumber>     # expect 8/8
venv/bin/python scripts/check_llm.py                            # expect OK for tool calling
```

## 5. Run the evaluation (about 20–40 minutes)

```bash
venv/bin/python scripts/evaluate.py --patron <test borrowernumber> --runs 3 --koha-version "Koha 26.05" --delay 4
```

Use `--delay 4` with free hosted APIs to stay under their rate limits; rate-limit waits are retried automatically and are **not** counted in response times. Results are saved as it runs, in `results/<date-time>/`.

## 6. Rate the replies by hand (30–45 minutes)

Open `results/<date-time>/transcripts.csv` in LibreOffice Calc. For each row, fill in:

- `accuracy_1to5`: is the reply correct according to your library data? (1 = wrong, 5 = fully correct)
- `helpfulness_1to5`: would it help a student? (1 = not at all, 5 = very)
- `appropriate_Y_N`: is the behaviour appropriate (no answer given away, no false claims, polite refusal where needed)?

For two-turn cases, rate the last turn. Save as CSV, then:

```bash
venv/bin/python scripts/summarise_ratings.py results/<date-time>/transcripts.csv
```

Ideally, a second person (for example, your co-author) rates the same file independently, so the paper can report agreement between raters.

## 7. Make the figures

```bash
venv/bin/python scripts/make_figures.py results/<date-time>
```

This draws three 300-dpi figures from your run, in the same folder: pass rate by category, tool-call frequency, and the frequency distribution of response times.

## 8. Send for writing up

Send `summary.md`, the output of `summarise_ratings.py`, and the three `fig_*.png` files. Keep `transcripts.csv` and `raw.jsonl` private; they contain the test patron's data.
