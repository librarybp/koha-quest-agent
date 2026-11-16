# Koha Quest Agent

Prototype of the agentic, gamified OPAC described in *An Agentic AI–Driven Gamified OPAC: Conceptual Design of Quest-Based Library Engagement in Koha* (Konch, Barpeta Polytechnic).

An LLM "Library Guide" inside the Koha OPAC offers optional learning quests. It reaches Koha only through a read-only MCP server, and only the quest engine can award XP and badges.

## Files

| File | Role |
| --- | --- |
| `koha_client.py` | Read-only Koha REST API client (GET only, OAuth2 client credentials) |
| `server.py` | MCP server: 12 tools, all scoped to the logged-in patron |
| `quest_engine.py` | Quest store (SQLite) and deterministic verification rules |
| `quests.json` | Quest templates written by the librarian (edit freely) |
| `library_info.json` | Hours, rules and services for `get_library_info` (edit before use) |
| `agent.py` | FastAPI service: login, LLM tool loop (any OpenAI-compatible API), MCP client |
| `opac_widget.js` | Chat panel for the OPAC (paste into `OPACUserJS`) |
| `scripts/install_local.sh` | One-step install on the Koha PC: Python, service, and Ollama if the PC can run it |
| `scripts/check_llm.py` | Checks the model: reachable, tool calling, speed |
| `scripts/check_koha.py` | Read-only check of your Koha: API key, endpoints, permissions, field names |
| `scripts/evaluate.py` | Technical evaluation: 24 cases against live Koha and a real model, scored automatically |
| `scripts/make_figures.py` | Draws the evaluation figures (pass rates, tool-call frequency, response times) |
| `scripts/summarise_ratings.py` | Summarises your manual ratings of the evaluation replies |
| `tests/` | Mock Koha API; MCP boundary test (18 checks) and agent loop test (7 checks) |

## Requirements

- Koha 23.05 or later (tested design target: 26.05). Uses `/oauth/token`, `/biblios`, `/biblios/{id}/items`, `/patrons/{id}`, `/checkouts` and `/auth/password/validation`.
- Ubuntu with Python 3.10+.
- A language model with tool calling, reached through an OpenAI-compatible API (`LLM_BASE_URL`). Koha, the MCP server and the agent are light; the model is the heavy part, and it can run on a different machine:
  - **Same PC** only if it has a CPU with AVX and 16 GB RAM or more (`qwen2.5:7b` via Ollama).
  - **Another PC on the campus network** with Ollama (a recent desktop with 16 GB RAM, ideally an NVIDIA GPU). On that PC: `curl -fsSL https://ollama.com/install.sh | sh`, `ollama pull qwen2.5:7b`, set `OLLAMA_HOST=0.0.0.0` for the Ollama service, and allow port 11434 from the Koha PC only. Then `LLM_BASE_URL=http://<that-PC-IP>:11434/v1`.
  - **Hosted provider** with an OpenAI-compatible endpoint. Conversations then leave the campus; tell students and get institutional approval.
- `install_local.sh` checks RAM and AVX and installs Ollama locally only when the PC can run it.

## Install on the local Koha PC (Ubuntu, instance `bpoly`)

1. **Koha settings** (staff interface):
   - Administration › System preferences: turn on `RESTOAuth2ClientCredentials`.
   - Create a staff patron, e.g. `api-guide`, with only these permissions: *catalogue*; *borrowers › list_borrowers*; *borrowers › api_validate_password*; *circulate › circulate_remaining_permissions*.
   - On that patron: More › Manage API keys › Generate. Copy the client id and secret.
2. **Find your ports:** `sudo koha-list` shows `bpoly`; `grep -E "Listen|VirtualHost" /etc/apache2/ports.conf /etc/apache2/sites-enabled/bpoly.conf` shows the OPAC and staff ports.
3. **Install:**
   ```bash
   unzip koha-quest-agent.zip && cd koha-quest-agent
   sudo bash scripts/install_local.sh
   sudo nano /opt/koha-quest-agent/.env    # KOHA_BASE_URL = staff address, client id/secret, OPAC_ORIGIN
   ```
4. **Check Koha** (use any test student's borrowernumber):
   ```bash
   cd /opt/koha-quest-agent
   sudo -u koha-quest venv/bin/python scripts/check_koha.py 7
   ```
   Fix any FAIL line; it names the missing permission or setting. Confirm the programme field: if your students' programme is not in *sort1*, change `PROGRAMME_FIELD`.
5. **Edit** `/opt/koha-quest-agent/quests.json` (real `biblio_id` values and answer keys from your catalogue) and `library_info.json`.
6. **Check the model:** `sudo -u koha-quest venv/bin/python scripts/check_llm.py` (aim for under 15 s per step).
7. **Start:** `sudo systemctl start koha-quest-agent` and check with `systemctl status koha-quest-agent`.
8. **OPAC:** paste `opac_widget.js` into Administration › System preferences › `OPACUserJS`, setting `AGENT_URL` to `http://<PC-IP>:8765`. If ufw is on: `sudo ufw allow 8765/tcp`.

Other computers on the campus network can use the guide through the PC's IP address. For access from outside the campus, put the agent behind Nginx with HTTPS.

## Test without Koha or a model

```bash
python tests/test_prototype.py   # MCP tools against a mock Koha
python tests/test_agent.py       # login and agent loop with a fake model
```

Runs the MCP server against a mock Koha API and checks tool scoping, privacy filtering, answer-key secrecy, verification rules, prompt-injection handling, opt-in/opt-out and department-score thresholds.

## Evaluation

See [EVALUATION.md](EVALUATION.md) to run the technical evaluation (`scripts/evaluate.py`) against your own Koha and a language model, and to summarise manual ratings.

## Safety design

- No tool accepts a patron id; the agent service sets it from a signed login token.
- `KohaClient` has no write methods.
- Answer keys stay in the quest engine; the model sees prompts, hints and verdicts only.
- Call numbers are hidden while a call-number quest for that title is active.
- Catalogue text is returned wrapped as data; the system prompt forbids following instructions in it.
- Department totals are shown only when a department has 10 or more participants.

## Compatibility

Works with the MCP Python SDK 1.x (`FastMCP`) and 2.x (`MCPServer`). Tested on 2026-10-06 with SDK 2.2.0 against a mock Koha API. Not yet tested against a live Koha instance; verify endpoint field names (`callnumber`, `checked_out_date`, `statistics_1`) on your version.
