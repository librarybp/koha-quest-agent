"""End-to-end test: MCP client -> server.py -> mock Koha. No LLM needed.

Run from the project folder:  python tests/test_prototype.py
"""
import asyncio
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

import mock_koha  # noqa: E402

PASS = []


def check(name, cond):
    PASS.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name)


def schema(t):
    return getattr(t, "input_schema", None) or getattr(t, "inputSchema", {})


def is_error(r):
    return bool(getattr(r, "is_error", None) or getattr(r, "isError", None))


def payload(result):
    text = "\n".join(c.text for c in result.content if getattr(c, "type", "") == "text")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


async def main():
    mock_koha.start(8399)
    db = os.path.join(tempfile.mkdtemp(), "quests.db")
    env = {**os.environ, "KOHA_BASE_URL": "http://127.0.0.1:8399", "KOHA_CLIENT_ID": "x",
           "KOHA_CLIENT_SECRET": "y", "KOHA_PATRON_ID": "7", "QUEST_DB": db}
    params = StdioServerParameters(command=sys.executable, args=[os.path.join(ROOT, "server.py")], env=env)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = {t.name: t for t in (await s.list_tools()).tools}
            check("12 tools exposed", len(tools) == 12)
            check("no tool takes a patron id",
                  all("patron" not in json.dumps(schema(t)) for t in tools.values()))

            res = payload(await s.call_tool("search_catalogue", {"query": "surveying"}))
            check("catalogue search returns record", isinstance(res, dict) and "Surveying" in json.dumps(res))

            prof = payload(await s.call_tool("get_my_profile", {}))
            check("profile returns programme", "Civil Engineering" in json.dumps(prof))
            check("profile hides contact details", "secret@example.com" not in json.dumps(prof)
                  and "9999999999" not in json.dumps(prof))

            r = payload(await s.call_tool("list_quests", {}))
            check("quests blocked before opt-in", r.get("error") == "not_joined")

            await s.call_tool("join_quests", {"department": "Civil"})
            avail = payload(await s.call_tool("list_quests", {}))
            dump = json.dumps(avail)
            check("level-1 quests offered", "ori-01" in dump and "il-01" not in dump)
            check("answer keys never exposed", "accepted" not in dump and "verify" not in dump)

            await s.call_tool("accept_quest", {"quest_id": "ori-01"})
            avl = payload(await s.call_tool("get_availability", {"biblio_id": 101}))
            check("call number hidden during active call-number quest", "690" not in json.dumps(avl))

            wrong = payload(await s.call_tool("submit_attempt", {"quest_id": "ori-01", "answer": "500 ABC"}))
            check("wrong answer gets a hint, no XP", wrong.get("verified") is False and "hint" in wrong)
            right = payload(await s.call_tool("submit_attempt", {"quest_id": "ori-01", "answer": "690 PUN"}))
            check("correct call number verified against Koha", right.get("verified") and right.get("xp_awarded") == 20)

            inj = payload(await s.call_tool("get_record", {"biblio_id": 103}))
            prog_before = payload(await s.call_tool("list_quests", {}))["progress"]["xp"]
            check("injected text is returned only as data", "1000 XP" in json.dumps(inj))
            prog_after = payload(await s.call_tool("list_quests", {}))["progress"]["xp"]
            check("no XP without quest engine verification", prog_before == prog_after == 20)

            await s.call_tool("accept_quest", {"quest_id": "read-01"})
            ret = payload(await s.call_tool("submit_attempt", {"quest_id": "read-01", "answer": "done"}))
            check("on-time return verified from circulation history", ret.get("verified") is True)

            await s.call_tool("accept_quest", {"quest_id": "read-02"})
            self_rep = payload(await s.call_tool("submit_attempt", {"quest_id": "read-02", "answer": "The Hindu"}))
            check("self-reported quest earns reduced XP", self_rep.get("xp_awarded") == 6)

            scores = payload(await s.call_tool("department_scores", {}))
            check("small departments hidden from scores", scores in ([], {"result": []}) or "Civil" not in json.dumps(scores))

            left = payload(await s.call_tool("leave_quests", {}))
            check("opt-out deletes quest data", left.get("data_deleted") is True)
            r = payload(await s.call_tool("list_quests", {}))
            check("after opt-out quests are blocked again", r.get("error") == "not_joined")

    print(f"\n{sum(PASS)}/{len(PASS)} checks passed")
    sys.exit(0 if all(PASS) else 1)


if __name__ == "__main__":
    asyncio.run(main())
