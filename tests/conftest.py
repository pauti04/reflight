import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
# The example agent is a script directory, not a package; make it importable.
sys.path.insert(0, str(REPO_ROOT / "examples" / "research_agent"))
