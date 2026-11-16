"""Technical evaluation of the Library Guide against a live Koha and a real language model.

Runs every case in eval/cases.json through the same agent code that students use
(agent.run_agent -> MCP server -> Koha), several times, and scores each run
automatically. Quest data goes to a fresh, separate database; Koha is only read.

Usage (from the project folder, with .env filled in):
    python scripts/evaluate.py --patron <test borrowernumber> [--runs 3] [--cases SRCH-1,SAFE-1]

Outputs in results/<timestamp>/:
    summary.md        tables for the paper
    summary.json      the same numbers, machine-readable
    transcripts.csv   every reply, with empty columns for your manual ratings
    raw.jsonl         full traces (tool calls and results)
transcripts.csv and raw.jsonl contain the test patron's data: keep them private.
"""
import argparse
import asyncio
import csv
import json
import os
import re
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def load_env(path):
    if not os.path.exists(path):
        sys.exit(f"Missing {path}. Copy .env.example to .env and fill it in.")
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


load_env(os.path.join(ROOT, ".env"))
os.environ.setdefault("AGENT_SECRET", "evaluation-only")
os.environ.setdefault("QUEST_TEMPLATES", os.path.join(ROOT, "quests.json"))
os.environ.setdefault("LIBRARY_INFO", os.path.join(ROOT, "library_info.json"))

import agent  # noqa: E402
from koha_client import KohaClient  # noqa: E402
from quest_engine import QuestEngine, norm  # noqa: E402

STOP = {"the", "and", "for", "with", "from", "into", "volume", "edition", "part", "introduction", "principles",
        "basic", "basics", "handbook", "text", "book", "test", "title"}


# ------------------------------------------------------------ test material from the live catalogue
def pick_material(koha: KohaClient) -> dict:
    biblios = koha.get("/biblios", {"_per_page": 100})
    title, topic2 = None, None
    for b in biblios:
        t = (b.get("title") or "").strip(" /:.")
        if len(t) < 6:
            continue
        try:
            if not koha.get_items(b["biblio_id"]):
                continue
        except Exception:
            continue
        if title is None:
            title = t
        else:
            words = [w for w in re.findall(r"[A-Za-z]{4,}", t) if w.lower() not in STOP]
            if words and topic2 is None:
                topic2 = words[0].lower()
        if title and topic2:
            break
    if not title:
        sys.exit("Could not find a catalogue record with items. Check the catalogue and API permissions.")
    words = [w for w in re.findall(r"[A-Za-z]{4,}", title) if w.lower() not in STOP]
    return {"TITLE": title, "TOPIC": (words[0] if words else title.split()[0]).lower(),
            "TOPIC2": topic2 or "engineering"}


def fill(text: str, mat: dict) -> str:
    for k, v in mat.items():
        text = text.replace("{" + k + "}", v)
    return text


# ------------------------------------------------------------ automatic checks
def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"



def tool_results(trace, name):
    return [s["result"] for s in trace if s.get("tool") == name]


def check(name, case_trace, replies, engine, patron, xp_before):
    reply_all = " ".join(replies)
    last = replies[-1] if replies else ""
    if name == "grounded_titles":
        titles = []
        for res in tool_results(case_trace, "search_catalogue"):
            # results arrive as one JSON value or one JSON object per item, depending on SDK version
            titles += [json.loads(f'"{t}"') for t in re.findall(r'"title":\s*"((?:[^"\\]|\\.)*)"', res)]
        titles = [t for t in titles if t]
        if not titles:
            return None  # nothing found: judge manually
        return any(norm(t[:25]) in norm(last) for t in titles)
    if name == "mentions_due_date":
        dates = []
        for res in tool_results(case_trace, "get_my_checkouts"):
            dates += re.findall(r"(\d{4})-(\d{2})-(\d{2})", res)
        if not dates:
            return None
        low = last.lower()
        for y, m, d in dates:
            dt = datetime(int(y), int(m), int(d))
            forms = {f"{y}-{m}-{d}", f"{int(d)} {dt:%B}".lower(), f"{dt:%B} {int(d)}".lower(),
                     f"{int(d)} {dt:%b}".lower(), f"{dt:%b} {int(d)}".lower(), f"{d}/{m}", f"{int(d)}/{int(m)}",
                     f"{d}-{m}", ordinal(int(d))}
            if any(f in low for f in forms):
                return True
        return False
    if name.startswith("no_answer_leak:"):
        q = engine.templates[name.split(":", 1)[1]]
        keys = [norm(a) for a in q["verify"]["params"]["accepted"]]
        return not any(k and k in norm(reply_all) for k in keys)
    if name == "xp_unchanged":
        return engine.total_xp(patron) == xp_before
    if name == "xp_increased":
        return engine.total_xp(patron) > xp_before
    if name == "still_joined":
        return engine.is_participant(patron)
    if name == "says_ai":
        return bool(re.search(r"\b(ai|artificial intelligence|assistant|not a human|language model)\b", last.lower()))
    raise ValueError(name)


def setup(kind, engine, patron):
    engine.leave(patron)
    if kind == "reset" or not kind:
        return
    engine.join(patron, "Evaluation")
    if kind.startswith("join_accept:"):
        engine.accept(patron, kind.split(":", 1)[1])


# ------------------------------------------------------------ run
async def run_case(case, run_no, mat, engine, patron, db):
    setup(case.get("setup"), engine, patron)
    xp_before = engine.total_xp(patron)
    history, replies, case_trace, turns_out = [], [], [], []
    error = None
    for turn in case["turns"]:
        msg = fill(turn, mat)
        trace = []
        t0 = time.perf_counter()
        try:
            reply = await agent.run_agent(patron, msg, history, trace, extra_env={"QUEST_DB": db})
        except Exception as e:  # network, model or tool failure
            reply, error = "", f"{type(e).__name__}: {e}"
        waited = sum(st.get("rate_limit_wait", 0) for st in trace)
        secs = time.perf_counter() - t0 - waited  # rate-limit waits are not response time
        tools = [s["tool"] for s in trace if "tool" in s]
        steps = sum(1 for s in trace if "llm_step" in s)
        turns_out.append({"message": msg, "reply": reply, "seconds": round(secs, 2),
                          "tools": tools, "llm_steps": steps, "trace": trace})
        history += [{"role": "user", "content": msg}, {"role": "assistant", "content": reply}]
        replies.append(reply)
        case_trace += trace
        if error:
            break
    called = {s["tool"] for s in case_trace if "tool" in s}
    expect, forbid = case.get("expect_tools", []), case.get("forbid_tools", [])
    result = {
        "case": case["id"], "category": case["category"], "run": run_no, "turns": turns_out, "error": error,
        "completed": error is None and all(r and r != agent.FALLBACK for r in replies),
        "tool_ok": (all(t in called for t in expect) if expect else None),
        "forbid_ok": (not (called & set(forbid)) if forbid else None),
        "checks": {},
    }
    if error is None:
        for c in case.get("checks", []):
            result["checks"][c] = check(c, case_trace, replies, engine, patron, xp_before)
    vals = [v for v in [result["tool_ok"], result["forbid_ok"], *result["checks"].values()] if v is not None]
    result["auto_pass"] = result["completed"] and all(vals)
    return result


def pct(xs):
    xs = [x for x in xs if x is not None]
    return (sum(1 for x in xs if x), len(xs))


def fmt(p):
    k, n = p
    return f"{k}/{n} ({100 * k / n:.1f}%)" if n else "n/a"


def summarise(results, meta):
    turns = [t for r in results for t in r["turns"] if t["reply"] or r["error"] is None]
    secs = [t["seconds"] for t in turns]
    s = {
        "meta": meta,
        "runs": len(results), "turns": len(turns),
        "completion": pct(r["completed"] for r in results),
        "tool_selection": pct(r["tool_ok"] for r in results),
        "forbidden_action_avoidance": pct(r["forbid_ok"] for r in results),
        "auto_pass": pct(r["auto_pass"] for r in results),
        "latency_s": {"mean": round(statistics.mean(secs), 1), "median": round(statistics.median(secs), 1),
                      "p90": round(sorted(secs)[max(0, int(0.9 * len(secs)) - 1)], 1),
                      "max": round(max(secs), 1)} if secs else {},
        "mean_llm_steps": round(statistics.mean(t["llm_steps"] for t in turns), 2) if turns else None,
        "mean_tool_calls": round(statistics.mean(len(t["tools"]) for t in turns), 2) if turns else None,
        "rate_limit_retries": sum(1 for t in turns for st in t["trace"] if "rate_limit_wait" in st),
        "checks": {}, "by_category": {}, "errors": [r["error"] for r in results if r["error"]],
    }
    names = sorted({c for r in results for c in r["checks"]})
    for c in names:
        s["checks"][c] = pct(r["checks"].get(c) for r in results if c in r["checks"])
    cats = defaultdict(list)
    for r in results:
        cats[r["category"]].append(r["auto_pass"])
    s["by_category"] = {k: pct(v) for k, v in cats.items()}
    return s


def write_outputs(results, s, out):
    os.makedirs(out, exist_ok=True)
    json.dump(s, open(os.path.join(out, "summary.json"), "w"), indent=2)
    with open(os.path.join(out, "raw.jsonl"), "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(out, "transcripts.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["case", "category", "run", "turn", "message", "reply", "tools_called", "seconds",
                    "auto_pass", "accuracy_1to5", "helpfulness_1to5", "appropriate_Y_N", "notes"])
        for r in results:
            for i, t in enumerate(r["turns"], 1):
                w.writerow([r["case"], r["category"], r["run"], i, t["message"], t["reply"],
                            " ".join(t["tools"]), t["seconds"], r["auto_pass"], "", "", "", ""])
    m = s["meta"]
    lines = [f"# Evaluation summary ({m['started']})", "",
             f"Model: {m['model']} at {m['llm_base_url_host']}; Koha: {m['koha']}; "
             f"{m['cases']} cases x {m['runs_per_case']} runs.", "",
             "## Table A. Overall results", "", "| Measure | Result |", "| --- | --- |",
             f"| Runs (cases x repetitions) | {s['runs']} |", f"| Agent turns | {s['turns']} |",
             f"| Completed without error | {fmt(s['completion'])} |",
             f"| Expected tool called | {fmt(s['tool_selection'])} |",
             f"| Forbidden action avoided | {fmt(s['forbidden_action_avoidance'])} |",
             f"| All automatic checks passed | {fmt(s['auto_pass'])} |"]
    for c, p in s["checks"].items():
        lines.append(f"| Check: {c} | {fmt(p)} |")
    if s["latency_s"]:
        L = s["latency_s"]
        lines += [f"| Response time per turn, s (mean / median / 90th pct / max) | "
                  f"{L['mean']} / {L['median']} / {L['p90']} / {L['max']} |",
                  f"| Mean model steps per turn | {s['mean_llm_steps']} |",
                  f"| Mean tool calls per turn | {s['mean_tool_calls']} |",
                  f"| Rate-limit retries (excluded from times) | {s['rate_limit_retries']} |"]
    lines += ["", "## Table B. Automatic pass rate by category", "", "| Category | Passed |", "| --- | --- |"]
    lines += [f"| {k} | {fmt(v)} |" for k, v in s["by_category"].items()]
    if s["errors"]:
        lines += ["", "## Errors", ""] + [f"- {e}" for e in s["errors"]]
    open(os.path.join(out, "summary.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patron", type=int, required=True, help="borrowernumber of a test patron")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--cases", default="", help="comma-separated case ids (default: all)")
    ap.add_argument("--koha-version", default="Koha (version not recorded)")
    ap.add_argument("--delay", type=float, default=0.0,
                    help="seconds to pause between cases (use 3-5 for free hosted APIs)")
    a = ap.parse_args()

    cases = json.load(open(os.path.join(ROOT, "eval", "cases.json"), encoding="utf-8"))
    if a.cases:
        keep = set(a.cases.split(","))
        cases = [c for c in cases if c["id"] in keep]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = os.path.join(ROOT, "results", stamp)
    os.makedirs(out, exist_ok=True)
    db = os.path.join(out, "eval_quests.db")

    koha = KohaClient()
    engine = QuestEngine(db, koha, os.environ["QUEST_TEMPLATES"])
    mat = pick_material(koha)
    print(f"Test material from your catalogue: {mat}")
    meta = {"started": datetime.now().isoformat(timespec="seconds"), "model": agent.LLM_MODEL,
            "llm_base_url_host": re.sub(r"^https?://([^/]+).*", r"\1", agent.LLM_BASE_URL),
            "koha": a.koha_version, "cases": len(cases), "runs_per_case": a.runs, "material": mat}

    results = []
    total = len(cases) * a.runs
    for run_no in range(1, a.runs + 1):
        for c in cases:
            r = await run_case(c, run_no, mat, engine, a.patron, db)
            results.append(r)
            secs = sum(t["seconds"] for t in r["turns"])
            print(f"[{len(results):>3}/{total}] {c['id']:<8} run {run_no}  "
                  f"{'PASS' if r['auto_pass'] else 'FAIL'}  {secs:5.1f}s  "
                  f"tools={','.join(t for tt in r['turns'] for t in tt['tools']) or '-'}"
                  + (f"  ERROR {r['error']}" if r["error"] else ""))
            write_outputs(results, summarise(results, meta), out)  # save as we go
            if a.delay:
                await asyncio.sleep(a.delay)
    engine.leave(a.patron)
    print(f"\nDone. Results in {out}\nOpen summary.md for the tables; rate replies in transcripts.csv.")


if __name__ == "__main__":
    asyncio.run(main())
