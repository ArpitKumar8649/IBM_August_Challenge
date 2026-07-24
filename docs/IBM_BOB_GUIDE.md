# IBM Bob — Setup & Usage Guide

> Fetched from the official docs at **bob.ibm.com** on 2026-07-24.

## ⚠️ Key correction: Bob is NOT a VS Code extension

Official docs, verbatim: *"Bob is a standalone IDE application and not an extension."*

IBM Bob ships as three things:
1. **Bob IDE** — a standalone desktop IDE (looks and feels like VS Code, but is its own app)
2. **Bob Shell** — the same AI agents in your terminal (interactive + scriptable)
3. **Bob Web** — browser access

## Trial & pricing facts

| | |
|---|---|
| Free trial | **40 Bobcoins for 30 days** |
| 1 Bobcoin | = $0.50 USD equivalent of compute |
| Pro plan | 40 Bobcoins/month; Pro+ 160; Ultra 500 |
| Login | **IBMid** (same account as IBM Cloud) via bob.ibm.com/login; Google sign-in works through IBMid |
| Requirements | macOS / Linux / Windows · 4 GB RAM min (8 GB recommended) · 500 MB disk · internet |

## Install (~5 minutes)

1. **Download:** https://bob.ibm.com/download → pick your OS (Windows .exe / Mac .pkg ARM or Intel / Linux .deb or .rpm)
2. Run the installer, accept defaults
3. Launch Bob → it opens a browser → **sign in with your IBMid** (create one free if needed — same as your IBM Cloud login)
4. Done — the chat panel is your main interface (`Ctrl+Alt+B` Windows/Linux, `Option+Cmd+B` Mac)

**For this codespace (Linux, headless):** the GUI IDE needs a display — install **Bob IDE on your own laptop** for the main build. Bob Shell (CLI) can run here if useful.

## The three modes (how you'll actually work)

| Mode | What it does | When to use it | Touches files? |
|------|--------------|----------------|----------------|
| **Plan** | Analyzes requirements, researches, designs implementation steps | Starting any module — get the design first | ❌ no (safe) |
| **Agent** | Writes, modifies, refactors code; full tool access (read/edit/execute/MCP/subagents) | Implementing the plan, fixing bugs | ✅ yes — you approve changes |
| **Ask** | Answers questions about the codebase | Understanding code, "why did this break?" | ❌ no |

**The workflow that wins:** Plan mode → review its design → Agent mode implements → you review the diff → iterate in chat. Bob shows you a plan and asks approval before running — use that gate.

## Features worth knowing

- **Approval workflow** — Bob proposes a plan before executing; review before approving
- **Subagents** — Bob spawns parallel focused agents for big tasks; you approve each spawn
- **Tools** — file read/write, terminal command execution, MCP servers for external tools
- **Literate coding** — write plain language directly in the editor, Bob generates the implementation in place
- **Rollback** — one-click undo of changes you didn't want
- **Context mentions** — @-mention files/symbols to focus Bob's context
- **Bobalytics** — usage tracking; screenshot this for the README's "How IBM Bob was used" section
- **.bobignore** — like .gitignore, keeps Bob out of data caches etc.

## Bobcoin budget strategy (important!)

The trial = 40 Bobcoins / 30 days, and the build window = 31 days. **Timing matters:**

- **Recommended:** install now, but **sign in for real on Aug 1** so the 30-day clock covers the whole build window. Do a 5-minute verification sign-in now if you want certainty it works (costs <1 Bobcoin), accepting the trial ends ~Aug 23 — then create a fresh trial account for the final week (the challenge FAQ guide documents exactly this procedure).
- **Spend Bobcoins where they count:** Plan mode for design (cheap), Agent mode for implementation (expensive but that's the point). Don't burn coins on trivia — use them on the engine, agent wiring, tests, and UI.
- **Log everything in `docs/BOB_LOG.md`** as you go — it feeds the required README section.

## Official quickstart (do this before Aug 1, ~30 min)

https://bob.ibm.com/docs/ide/getting-started/quickstart — build a React UI for a Node.js Express API (repo: github.com/IBM/bob-demo). Teaches modes, the approval workflow, and agentic iteration. Perfect warm-up.

## Docs worth bookmarking

- Install: bob.ibm.com/docs/ide/getting-started/install
- Best practices: bob.ibm.com/docs/ide/getting-started/best-practices
- Modes: bob.ibm.com/docs/ide/features/modes
- Subagents: bob.ibm.com/docs/ide/features/subagents
- Writing effective prompts: bob.ibm.com/docs/ide/tutorials/write-effective-prompts
- Bob Shell install: bob.ibm.com/docs/shell/getting-started/install-and-setup
- FAQ: bob.ibm.com/docs/ide/faq
