# IBM Bob Usage Log

> Running log of how IBM Bob was used as the primary development tool. Entries feed the README's required "How IBM Bob was used" section — log as you go, not at the end. Capture: what you asked, what Bob produced, what you iterated on, time saved.

| Date | Module | What Bob did | Prompt pattern / notes | Outcome |
|------|--------|--------------|------------------------|---------|
| 2026-07-24 | Planning | (pre-launch — planning done with Claude; project code will be built with Bob from Aug 1) | — | — |

## Patterns worth documenting for the README

- **Module generation:** e.g. "generate `engine/ingest/celestrak.py` from this spec + pydantic model" → review → iterate
- **Test generation:** "write pytest cases for SGP4 propagation against Vallado's reference TLEs"
- **Debugging loops:** the SkillsBuild troubleshooting pattern (analyze → recommend → apply → validate)
- **Refactoring:** "split screen.py into coarse/fine stages"
- **Docs:** docstrings, README drafts from code
