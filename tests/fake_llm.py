"""A rule-based stand-in for an OpenAI-compatible model, used only to test the evaluation pipeline."""
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

QUEST_NAMES = {"know the rules": "ori-02", "standards matter": "il-01"}


def decide(messages):
    last_user = next(m["content"] for m in reversed(messages) if m["role"] == "user")
    low = last_user.lower()
    if messages[-1]["role"] == "tool":
        data = messages[-1]["content"]
        if "not_joined" in data:
            return {"content": "You have not joined Library Quests yet. Would you like to join?"}
        return {"content": f"I am an AI library guide. Here is what I found: {data}"}

    def call(name, args=None):
        return {"content": "", "tool_calls": [{"id": "c1", "type": "function",
                "function": {"name": name, "arguments": json.dumps(args or {})}}]}
    if "sign me up" in low:
        return call("join_quests", {"department": "Civil"})
    if "my answer is" in low:
        qid = next((v for k, v in QUEST_NAMES.items() if k in low), "ori-02")
        return call("submit_attempt", {"quest_id": qid, "answer": last_user.split("my answer is", 1)[1].strip(" .")})
    if any(w in low for w in ("hours", "borrow", "indian standards")):
        return call("get_library_info", {})
    if "on loan" in low:
        return call("get_my_checkouts")
    if "category" in low:
        return call("get_my_profile")
    if "quests can i" in low or "quests i can" in low:
        return call("list_quests")
    m = re.search(r"(?:about|on|called) ([A-Za-z ]+?)[?.]", last_user)
    if m and "quest" not in low:
        return call("search_catalogue", {"query": m.group(1).split()[0]})
    return {"content": "I am an AI library guide and cannot do that; please ask the librarian."}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        msg = {"role": "assistant", **decide(req["messages"])}
        out = json.dumps({"choices": [{"message": msg}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(out)


def start(port=8397):
    srv = HTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
