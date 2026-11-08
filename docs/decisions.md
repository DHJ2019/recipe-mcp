# Decisions

Append-only. One line per decision: date, decision, why. Newest at the bottom.
Never cite commit ids or private issue numbers here. The public copy has different history.

- 2026-09-19 (spec v3.3). Telegram replaces WhatsApp as the MVP channel, as one shared group with Alex, Sam and the bot. Why: one group replaces two bot conversations, and a WhatsApp Business sender needs a business portfolio, a public webhook and per-message cost.
- 2026-09-19 (spec v3.3). The Telegram bot uses long polling. No public webhook or tunnel. Why: nothing on the Mac is exposed to the network.
- 2026-09-19 (spec v3.3). WhatsApp history comes in only through a chat-export import, and the import is idempotent. Why: periodic re-exports can be repeated without duplicates.
- 2026-09-19 (spec v3.3). Corrections go through a fifth MCP tool, `correct_recipe`. Why: every channel uses the same interface.
- 2026-09-19 (spec v3.4). Claude Code is the brain. The application calls no hosted model API, and the MCP server is deterministic and needs no API key. Why: the agent that calls the server already understands language, and the server stays testable.
- 2026-09-19 (spec v3.4). `save_recipe` takes structured fields, and `correct_recipe(proposed_by_agent=true)` stores an agent's classification as a proposal. Why: an agent that already parsed the text can save without a server-side model, and a person's correction still wins.
- 2026-09-19 (spec v3.4). The Telegram host calls the Bot API directly and resolves ratings, replies, ordinal references and time corrections without the brain. Why: one dependency fewer, and the common cases are deterministic and fast.
- 2026-09-19 (spec v3.4). Unattended `claude -p` runs use the household's own subscription, and the repository embeds no credentials. A local model is the fallback brain. Why: no API bill, and no secret in the repository.
- 2026-09-23 (spec v3.5). Every food on an ingredient line counts, alternatives included, and a food type counts only when it is listed. Why: dietary labels must never be inferred from a dish name.
- 2026-09-23 (spec v3.5). A recipe can reach a stricter diet only through choices its own lines state ("or", optional, garnish). Why: offering "vegan if you use vegetable broth" is useful, and inventing swaps is not.
- 2026-09-23 (spec v3.5). People can correct an ingredient's food types for one recipe, but cannot set dietary suitability directly. Why: the dietary rules stay the only judge, and each correction becomes a regression case.
- 2026-11-06. The backlog lives in the spec's Roadmap section, not in a separate ideas file. Why: the public copy is published from this repository, so the backlog travels with the spec and readers of either copy see it.
- 2026-11-06. CLAUDE.md is `@AGENTS.md`. Why: one file for both tools means nothing to keep in sync.
