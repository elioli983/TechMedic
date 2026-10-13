from sqlcipher3 import dbapi2 as sqlite3
import tempfile
import unittest
from pathlib import Path

from techmedic import database


class DatabaseTests(unittest.TestCase):
    def test_connection_is_closed_after_successful_context(self):
        """Windows must be able to release/delete a test DB immediately."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "closed.db"
            database.init_db(db_path)
            with database._connect(db_path) as con:
                self.assertEqual(con.execute("SELECT 1").fetchone()[0], 1)
            with self.assertRaises(sqlite3.ProgrammingError):
                con.execute("SELECT 1")

    def test_connection_rolls_back_and_closes_after_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "rollback.db"
            database.init_db(db_path)
            with self.assertRaisesRegex(RuntimeError, "synthetic transaction failure"):
                with database._connect(db_path) as con:
                    con.execute(
                        "INSERT INTO cases(id,title,created_at,updated_at) VALUES(?,?,?,?)",
                        ("case-fi", "temporary", "2026-10-10", "2026-10-10"),
                    )
                    raise RuntimeError("synthetic transaction failure")
            with self.assertRaises(sqlite3.ProgrammingError):
                con.execute("SELECT 1")
            with database._connect(db_path) as check:
                self.assertEqual(check.execute("SELECT count(*) FROM cases").fetchone()[0], 0)

    def test_case_and_turn_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            database.init_db(db_path)
            case_id = database.create_case(db_path, "GPU problem", device_type="PC")
            database.add_turn(
                db_path,
                case_id,
                "GPU unavailable",
                {"case_summary": "GPU issue", "status": "investigating"},
                {"answers": {"evidence_sufficient": {"type": "noul", "noul": 0.2}}},
                {"blocked": False, "risk_level": "low", "warnings": [], "blocked_reasons": []},
                "Run a version check.",
                research={"performed": True, "query": "official docs", "sources": [{"id": "R1"}]},
            )
            turns = database.get_turns(db_path, case_id)
            self.assertEqual(len(turns), 1)
            self.assertEqual(turns[0]["diagnostic_state"]["case_summary"], "GPU issue")
            self.assertTrue(turns[0]["research"]["performed"])
            self.assertEqual(database.get_latest_state(db_path, case_id)["status"], "investigating")

    def test_long_case_title_is_not_truncated(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            database.init_db(db_path)
            original = "A long diagnostic summary " + ("with useful technical detail " * 8)
            case_id = database.create_case(db_path, "short")
            database.update_case(db_path, case_id, title=original)
            self.assertEqual(database.get_case(db_path, case_id)["title"], original)


    def test_init_db_migrates_v14_turns_table_with_research_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "legacy.db"
            ctx = database._connect(db_path)
            con = ctx.__enter__()
            con.executescript(
                """
                CREATE TABLE cases (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, device_type TEXT NOT NULL DEFAULT '',
                    manufacturer TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '',
                    operating_system TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'investigating',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, user_text TEXT NOT NULL,
                    diagnostic_state_json TEXT NOT NULL, jev_result_json TEXT NOT NULL, safety_json TEXT NOT NULL,
                    assistant_text TEXT NOT NULL, created_at TEXT NOT NULL
                );
                """
            )
            ctx.__exit__(None, None, None)
            database.init_db(db_path)
            ctx = database._connect(db_path)
            con = ctx.__enter__()
            cols = {row[1] for row in con.execute("PRAGMA table_info(turns)").fetchall()}
            ctx.__exit__(None, None, None)
            self.assertIn("research_json", cols)


if __name__ == "__main__":
    unittest.main()
