"""Quest engine: the only component that can award XP and badges.

The engine verifies quest attempts with deterministic rules against Koha
data or librarian-written answer keys. Answer keys never leave this module;
the agent receives only the quest prompt, hints and the verdict.
"""
import json
import re
import sqlite3
from datetime import datetime, timezone

LEVELS = [(0, "Explorer"), (100, "Navigator"), (300, "Scholar")]
BADGE_AFTER = 3          # verified quests in one family earn that family's badge
SELF_REPORT_FACTOR = 0.3  # self-reported quests earn reduced XP and no badge
MIN_TEAM_SIZE = 10        # department totals shown only above this size

SCHEMA = """
CREATE TABLE IF NOT EXISTS participants (
  patron_id INTEGER PRIMARY KEY, department TEXT, joined_at TEXT);
CREATE TABLE IF NOT EXISTS user_quests (
  patron_id INTEGER, quest_id TEXT, state TEXT, accepted_at TEXT,
  completed_at TEXT, attempts INTEGER DEFAULT 0,
  PRIMARY KEY (patron_id, quest_id));
CREATE TABLE IF NOT EXISTS awards (
  patron_id INTEGER, quest_id TEXT, family TEXT, xp INTEGER,
  verified INTEGER, awarded_at TEXT);
CREATE TABLE IF NOT EXISTS badges (
  patron_id INTEGER, badge TEXT, awarded_at TEXT, PRIMARY KEY (patron_id, badge));
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9.]", "", str(text).lower())


class QuestEngine:
    def __init__(self, db_path: str, koha, templates_path: str):
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.koha = koha
        with open(templates_path, encoding="utf-8") as f:
            self.templates = {q["id"]: q for q in json.load(f)}

    # -- participation ----------------------------------------------------
    def join(self, patron_id: int, department: str) -> None:
        self.db.execute("INSERT OR IGNORE INTO participants VALUES (?,?,?)",
                        (patron_id, department, now()))
        self.db.commit()

    def leave(self, patron_id: int) -> None:
        """Opt out and delete all quest data for this patron."""
        for table in ("participants", "user_quests", "awards", "badges"):
            self.db.execute(f"DELETE FROM {table} WHERE patron_id=?", (patron_id,))
        self.db.commit()

    def is_participant(self, patron_id: int) -> bool:
        return self.db.execute("SELECT 1 FROM participants WHERE patron_id=?",
                               (patron_id,)).fetchone() is not None

    # -- quests -----------------------------------------------------------
    @staticmethod
    def public_view(q: dict) -> dict:
        """What the agent may see: never the answer key or rule parameters."""
        return {k: q[k] for k in ("id", "family", "level", "title", "prompt", "xp", "biblio_id") if k in q}

    def available(self, patron_id: int, level: int | None = None) -> list[dict]:
        done = {r["quest_id"] for r in self.db.execute(
            "SELECT quest_id FROM user_quests WHERE patron_id=?", (patron_id,))}
        xp = self.total_xp(patron_id)
        max_level = 1 if xp < 100 else 2 if xp < 300 else 3
        return [self.public_view(q) for q in self.templates.values()
                if q["id"] not in done and q["level"] <= (level or max_level)]

    def accept(self, patron_id: int, quest_id: str) -> dict:
        if quest_id not in self.templates:
            return {"ok": False, "message": "Unknown quest."}
        self.db.execute(
            "INSERT OR IGNORE INTO user_quests (patron_id, quest_id, state, accepted_at) "
            "VALUES (?,?, 'accepted', ?)", (patron_id, quest_id, now()))
        self.db.commit()
        return {"ok": True, "quest": self.public_view(self.templates[quest_id])}

    def submit(self, patron_id: int, quest_id: str, answer: str) -> dict:
        row = self.db.execute("SELECT * FROM user_quests WHERE patron_id=? AND quest_id=?",
                              (patron_id, quest_id)).fetchone()
        if row is None:
            return {"verified": False, "message": "Accept the quest first."}
        if row["state"] == "verified":
            return {"verified": True, "message": "Already completed."}
        q = self.templates[quest_id]
        self.db.execute("UPDATE user_quests SET attempts=attempts+1 WHERE patron_id=? AND quest_id=?",
                        (patron_id, quest_id))
        ok, verified_by_data = self._verify(patron_id, q, answer, row["accepted_at"])
        if not ok:
            self.db.commit()
            return {"verified": False, "hint": q.get("hint", "Try again.")}
        xp = q["xp"] if verified_by_data else int(q["xp"] * SELF_REPORT_FACTOR)
        self.db.execute("UPDATE user_quests SET state='verified', completed_at=? "
                        "WHERE patron_id=? AND quest_id=?", (now(), patron_id, quest_id))
        self.db.execute("INSERT INTO awards VALUES (?,?,?,?,?,?)",
                        (patron_id, quest_id, q["family"], xp, int(verified_by_data), now()))
        badge = self._maybe_badge(patron_id, q["family"]) if verified_by_data else None
        self.db.commit()
        return {"verified": True, "xp_awarded": xp, "new_badge": badge,
                "level": self.level(patron_id), "reflect": q.get("reflect")}

    # -- verification rules ------------------------------------------------
    def _verify(self, patron_id: int, q: dict, answer: str, accepted_at: str) -> tuple[bool, bool]:
        rule, p = q["verify"]["type"], q["verify"].get("params", {})
        if rule == "answer":
            return norm(answer) in {norm(a) for a in p["accepted"]}, True
        if rule == "callnumber":
            items = self.koha.get_items(p["biblio_id"])
            calls = {norm(i.get("callnumber") or "") for i in items}
            return norm(answer) in calls or any(c.startswith(norm(answer)) and len(norm(answer)) >= 3
                                                for c in calls), True
        if rule == "checkout_return":
            for c in self.koha.get_checkouts(patron_id, history=True):
                out, back, due = c.get("checkout_date"), c.get("checkin_date"), c.get("due_date")
                if out and back and due and out >= accepted_at[:10] and back[:10] <= due[:10]:
                    return True, True
            return False, True
        if rule == "citation":
            text = answer.strip()
            checks = {
                "author": re.search(r"^[A-Z][A-Za-z'\-]+,\s*[A-Z]", text),
                "year": re.search(r"\b(19|20)\d{2}\b", text),
                "title": len(re.split(r"[.,]", text)) >= 3,
                "publisher": re.search(r"[A-Za-z]+\s*[:,]\s*[A-Z][A-Za-z&.\s]+", text),
            }
            return all(checks[k] for k in p.get("required", checks)), True
        if rule == "self":
            return bool(answer.strip()), False
        raise ValueError(f"Unknown rule {rule}")

    # -- progress -----------------------------------------------------------
    def total_xp(self, patron_id: int) -> int:
        return self.db.execute("SELECT COALESCE(SUM(xp),0) FROM awards WHERE patron_id=?",
                               (patron_id,)).fetchone()[0]

    def level(self, patron_id: int) -> str:
        xp = self.total_xp(patron_id)
        return [name for floor, name in LEVELS if xp >= floor][-1]

    def _maybe_badge(self, patron_id: int, family: str) -> str | None:
        n = self.db.execute("SELECT COUNT(*) FROM awards WHERE patron_id=? AND family=? AND verified=1",
                            (patron_id, family)).fetchone()[0]
        if n >= BADGE_AFTER:
            badge = family.replace("_", " ").title() + " Badge"
            cur = self.db.execute("INSERT OR IGNORE INTO badges VALUES (?,?,?)", (patron_id, badge, now()))
            return badge if cur.rowcount else None
        return None

    def progress(self, patron_id: int) -> dict:
        badges = [r["badge"] for r in self.db.execute(
            "SELECT badge FROM badges WHERE patron_id=?", (patron_id,))]
        active = [r["quest_id"] for r in self.db.execute(
            "SELECT quest_id FROM user_quests WHERE patron_id=? AND state='accepted'", (patron_id,))]
        return {"xp": self.total_xp(patron_id), "level": self.level(patron_id),
                "badges": badges, "active_quests": active}

    def department_scores(self) -> list[dict]:
        """Aggregate team totals only; small teams are hidden to protect privacy."""
        rows = self.db.execute(
            "SELECT p.department, COUNT(DISTINCT p.patron_id) n, COALESCE(SUM(a.xp),0) xp "
            "FROM participants p LEFT JOIN awards a ON a.patron_id=p.patron_id "
            "GROUP BY p.department HAVING n >= ? ORDER BY xp DESC", (MIN_TEAM_SIZE,))
        return [{"department": r["department"], "participants": r["n"], "total_xp": r["xp"]} for r in rows]
