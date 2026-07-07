import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
# The example agents are script directories, not packages; make them importable.
sys.path.insert(0, str(REPO_ROOT / "examples" / "research_agent"))
sys.path.insert(0, str(REPO_ROOT / "examples" / "flaky_agent"))
