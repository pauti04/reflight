"""Three tools for the example research agent: a stubbed web search (canned
corpus, so runs don't depend on a live search API), a safe calculator, and a
note writer. The calculator raising on bad math (e.g. divide by zero) is our
seeded failure mode for Sprint 0.
"""

from __future__ import annotations

import ast
import json
import operator
from pathlib import Path
from typing import Callable

TOOL_SPECS = [
    {
        "name": "web_search",
        "description": "Search the web for facts. Returns text snippets from search results.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "The search query."}},
            "required": ["query"],
        },
    },
    {
        "name": "calculator",
        "description": (
            "Evaluate an arithmetic expression. Supports numbers, parentheses, "
            "and the operators + - * / // % **."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "e.g. '(2 + 3) * 4'"}
            },
            "required": ["expression"],
        },
    },
    {
        "name": "save_note",
        "description": "Save a research note to disk so it isn't lost.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["title", "content"],
        },
    },
]

_CORPUS = {
    "tokyo population": (
        "Tokyo metropolitan area population, 2025 estimate: 37,400,068. "
        "(demo corpus)"
    ),
    "mount everest height": "Mount Everest stands 8,848.86 m above sea level. (demo corpus)",
    "speed light": "The speed of light in vacuum is 299,792,458 m/s. (demo corpus)",
    "python release year": "Python was first released in 1991 by Guido van Rossum. (demo corpus)",
}

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(expression: str) -> float:
    def walk(node: ast.AST) -> float:
        match node:
            case ast.Expression(body=body):
                return walk(body)
            case ast.Constant(value=v) if isinstance(v, (int, float)):
                return v
            case ast.BinOp(left=left, op=op, right=right) if type(op) in _OPS:
                return _OPS[type(op)](walk(left), walk(right))
            case ast.UnaryOp(op=op, operand=operand) if type(op) in _OPS:
                return _OPS[type(op)](walk(operand))
            case _:
                raise ValueError(f"unsupported syntax in expression: {ast.dump(node)}")

    return walk(ast.parse(expression, mode="eval"))


def make_tools(notes_dir: Path) -> dict[str, Callable[..., str]]:
    def web_search(query: str) -> str:
        q = query.lower()
        hits = [text for key, text in _CORPUS.items() if all(w in q for w in key.split())]
        if not hits:
            hits = [text for key, text in _CORPUS.items() if any(w in q for w in key.split())]
        if not hits:
            return f"No results for {query!r}. (stub corpus)"
        return json.dumps({"results": hits})

    def calculator(expression: str) -> str:
        result = _safe_eval(expression)
        if isinstance(result, float) and result.is_integer():
            result = int(result)
        return str(result)

    def save_note(title: str, content: str) -> str:
        notes_dir.mkdir(parents=True, exist_ok=True)
        slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in title.lower()).strip("-")
        path = notes_dir / f"{slug[:60] or 'note'}.md"
        path.write_text(f"# {title}\n\n{content}\n", encoding="utf-8")
        return f"Saved note: {path.name}"

    return {"web_search": web_search, "calculator": calculator, "save_note": save_note}
