"""Framework adapters: instrument popular agent frameworks without changing
their code. Each adapter routes the framework's LLM client and tools through a
Reflight session, so record/replay/fork/promote all work as usual."""
