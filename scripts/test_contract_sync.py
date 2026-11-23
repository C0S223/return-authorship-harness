"""CLAUDE.md and AGENTS.md are one contract under two names: Claude Code reads
the first, Codex the second. They must stay byte-identical.

    python scripts/test_contract_sync.py
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class ContractSync(unittest.TestCase):
    def test_the_two_contract_files_are_identical(self):
        self.assertEqual((ROOT / "CLAUDE.md").read_bytes(), (ROOT / "AGENTS.md").read_bytes())


if __name__ == "__main__":
    unittest.main()
