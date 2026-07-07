"""LangChain / LangGraph adapter.

Record and replay LangGraph agents without changing agent code: the adapter
injects the Reflight session underneath the ChatOpenAI client and wraps
LangChain tools, so the framework never knows the difference.

    from reflight.adapters.langchain import instrument

    session = reflight.record("runs/lg-run", task=task)     # or reflight.replay(...)
    model, tools = instrument(session, ChatOpenAI(model="gpt-4o-mini"), tools)
    agent = create_react_agent(model, tools)                # unchanged LangGraph code

Sync paths only for now (`graph.invoke` / `model.invoke`) — async client
injection is tracked in NOTES.md. Reflight itself takes no langchain
dependency; the adapter just pokes at two documented attributes.
"""

from __future__ import annotations

from typing import Any, Sequence


def instrument_chat_model(session: Any, chat_model: Any, openai_client: Any = None) -> Any:
    """Route the model's completions through the session.

    Works with ChatOpenAI (and subclasses) — anything that exposes
    `root_client` (an openai.OpenAI) and `client` (its chat.completions).
    Pass `openai_client` to override the underlying client (e.g. a scripted
    fake in tests); replay sessions ignore it entirely.
    """
    underlying = openai_client if openai_client is not None else getattr(
        chat_model, "root_client", None
    )
    if underlying is None and session.mode == "record":
        try:  # fall back to an env-configured client (OPENAI_API_KEY etc.)
            from openai import OpenAI

            underlying = OpenAI()
        except Exception as exc:
            raise ValueError(
                f"cannot instrument {type(chat_model).__name__}: no root_client and no "
                f"env-configured OpenAI client ({exc}) — pass openai_client= explicitly"
            ) from exc
    facade = session.wrap_openai(underlying)
    try:
        chat_model.client = facade.chat.completions
    except (AttributeError, ValueError) as exc:
        raise ValueError(
            f"cannot instrument {type(chat_model).__name__}: client injection failed ({exc})"
        ) from exc
    return chat_model


def _rewrap(session: Any, func: Any) -> Any:
    """Wrap the ORIGINAL function even if func was instrumented before —
    tool objects are long-lived (module level, notebooks), and wrapping a
    stale session's wrapper would replay against the wrong run."""
    original = getattr(func, "__reflight_original__", func)
    wrapped = session.tool(original)
    wrapped.__reflight_original__ = original
    return wrapped


def instrument_tools(session: Any, tools: Sequence[Any]) -> list[Any]:
    """Wrap LangChain tools (or plain callables) so calls are recorded/replayed."""
    wrapped = []
    for tool in tools:
        if callable(tool) and getattr(tool, "func", None) is None and not hasattr(tool, "invoke"):
            wrapped.append(_rewrap(session, tool))  # a plain function
            continue
        func = getattr(tool, "func", None)
        if func is None:
            raise ValueError(
                f"cannot instrument tool {getattr(tool, 'name', tool)!r}: it has no sync "
                ".func (coroutine-only tools aren't supported yet)"
            )
        tool.func = _rewrap(session, func)
        wrapped.append(tool)
    return wrapped


def instrument(
    session: Any, chat_model: Any, tools: Sequence[Any] = (), openai_client: Any = None
) -> tuple[Any, list[Any]]:
    """One call: (model, tools) ready for create_react_agent / your graph."""
    return (
        instrument_chat_model(session, chat_model, openai_client=openai_client),
        instrument_tools(session, tools),
    )
