"""Sprint 10: the pytest plugin — promoted tests inside a normal test run."""

from pathlib import Path

import main as example
from flaky_model import FlakyAnthropic
from tools import make_tools

import reflight
from reflight.testing import promote

pytest_plugins = ["pytester"]

REPO_ROOT = Path(__file__).resolve().parents[1]
RESEARCH_AGENT = REPO_ROOT / "examples" / "research_agent"
FLAKY_AGENT = REPO_ROOT / "examples" / "flaky_agent"
TASK = "What is the population of Tokyo, and what is that number divided by 2?"

AGENT_MODULE = f"""
import sys
sys.path.insert(0, {str(RESEARCH_AGENT)!r})
sys.path.insert(0, {str(FLAKY_AGENT)!r})
from main import run_agent
from tools import make_tools
from flaky_model import FlakyAnthropic

def agent(session, task):
    return run_agent(session, task)

def tools(run_dir):
    return make_tools(run_dir / "notes")

def client():
    return FlakyAnthropic(0)  # the fixed model
"""

INI = """
[pytest]
reflight_agent = my_agent:agent
reflight_tools_factory = my_agent:tools
reflight_client_factory = my_agent:client
"""


def _promote_run(root: Path, seed: int, run_id: str) -> None:
    db = root / "reflight.db"
    run_dir = root / "runs" / run_id
    session = reflight.record(run_dir, task=TASK, db_path=db)
    session.wrap(FlakyAnthropic(seed))
    session._tools.update(make_tools(run_dir / "notes"))
    example.run_agent(session, TASK)
    promote(db, run_id, tests_dir=root / "agent_tests")


def test_promoted_tests_collect_and_run(pytester):
    root = Path(pytester.path)
    _promote_run(root, 0, "good-run")  # passing run: regression pin holds via replay
    _promote_run(root, 1, "loop-run")  # failing run: loop reproduces via replay,
    #                                     then re-verifies live on the FIXED model → passes

    pytester.makepyfile(my_agent=AGENT_MODULE)
    pytester.makefile(".ini", pytest=INI)

    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=2)
    result.stdout.fnmatch_lines(["*good-run*PASSED*", "*loop-run*PASSED*"])


def test_failing_promoted_test_reports_readably(pytester):
    root = Path(pytester.path)
    _promote_run(root, 1, "loop-run")

    # no client factory → the replay failure stands and reports the findings
    pytester.makepyfile(my_agent=AGENT_MODULE)
    pytester.makefile(
        ".ini",
        pytest="""
[pytest]
reflight_agent = my_agent:agent
reflight_tools_factory = my_agent:tools
""",
    )

    result = pytester.runpytest()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*promoted test 'loop-run' failed (replay):*", "*loop*"])


def test_plugin_is_inert_without_configuration(pytester):
    root = Path(pytester.path)
    _promote_run(root, 0, "good-run")  # agent_tests/ exists but no reflight_agent ini

    result = pytester.runpytest()
    assert result.parseoutcomes().get("errors") is None
    # nothing collected from the yaml — the plugin stayed out of the way
    result.stdout.fnmatch_lines(["*no tests ran*"])
