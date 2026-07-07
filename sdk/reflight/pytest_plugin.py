"""pytest plugin: promoted tests run inside your normal test suite.

Point pytest at your agent in pytest.ini (or pyproject's [tool.pytest.ini_options]):

    [pytest]
    reflight_agent = my_pkg.agent:run_agent            # agent(session, task)
    reflight_tools_factory = my_pkg.agent:make_tools   # optional: run_dir -> dict
    reflight_client_factory = my_pkg.agent:make_client # optional: () -> live client
                                                       #   (enables live re-verify)
    reflight_tests_dir = agent_tests                   # optional, this is the default

Every `agent_tests/*.yaml` written by `reflight promote` then collects as a
test item. Replay-first economics apply: passing tests cost $0.00; failures
re-verify live when a client factory is configured.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addini("reflight_agent", "dotted path (module:attr) to agent(session, task)")
    parser.addini("reflight_tools_factory", "dotted path to tools factory: run_dir -> dict")
    parser.addini("reflight_client_factory", "dotted path to zero-arg live client factory")
    parser.addini("reflight_tests_dir", "directory of promoted tests", default="agent_tests")


def _load(dotted: str, rootpath: Path | None = None):
    module_name, _, attr = dotted.partition(":")
    if not attr:
        raise pytest.UsageError(
            f"reflight: expected 'module:attr', got {dotted!r} (missing ':')"
        )
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError:
        # the agent module usually lives at the project root — make that work
        # without requiring users to package it
        if rootpath is None or str(rootpath) in sys.path:
            raise
        sys.path.insert(0, str(rootpath))
        module = importlib.import_module(module_name)
    return getattr(module, attr)


def pytest_collect_file(parent: pytest.Collector, file_path: Path):
    config = parent.config
    if not config.getini("reflight_agent"):
        return None  # plugin not configured for this project
    tests_dir = config.getini("reflight_tests_dir")
    if file_path.suffix in (".yaml", ".yml") and file_path.parent.name == Path(tests_dir).name:
        return ReflightFile.from_parent(parent, path=file_path)
    return None


class ReflightFailure(Exception):
    def __init__(self, result):
        self.result = result
        super().__init__(str(result))


class ReflightFile(pytest.File):
    def collect(self):
        from .testing import load_test

        spec = load_test(self.path)
        yield ReflightItem.from_parent(self, name=str(spec["name"]), spec=spec)


class ReflightItem(pytest.Item):
    def __init__(self, *, spec: dict, **kwargs):
        super().__init__(**kwargs)
        self.spec = spec

    def runtest(self) -> None:
        from .testing import run_test

        ini = self.config.getini
        root = self.config.rootpath
        agent = _load(ini("reflight_agent"), root)
        tools_factory = (
            _load(ini("reflight_tools_factory"), root) if ini("reflight_tools_factory") else None
        )
        client_factory = (
            _load(ini("reflight_client_factory"), root)
            if ini("reflight_client_factory")
            else None
        )
        result = run_test(
            self.spec,
            agent,
            live_client_factory=client_factory,
            tools_factory=tools_factory,
        )
        self.user_properties.append(("reflight_mode", result.mode))
        if not result.passed:
            raise ReflightFailure(result)

    def repr_failure(self, excinfo, style=None):
        if isinstance(excinfo.value, ReflightFailure):
            result = excinfo.value.result
            lines = [f"promoted test {self.name!r} failed ({result.mode}):"]
            lines += [f"  · {failure}" for failure in result.failures]
            if result.mode == "diverged":
                lines.append(
                    "  hint: configure reflight_client_factory to re-verify live "
                    "after behavior changes"
                )
            return "\n".join(lines)
        return super().repr_failure(excinfo, style=style)

    def reportinfo(self):
        return self.path, 0, f"reflight promoted test: {self.name}"
