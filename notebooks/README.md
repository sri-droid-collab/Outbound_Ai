# Learning notebooks: how the OutboundAI agents work

Four self-contained notebooks that rebuild the project's AI agents step by step. They are written for learning, so
each one runs **offline with a fake LLM** by default and switches to a real model when you add an API key.

| # | Notebook | Agent | Status in repo |
|---|---|---|---|
| 00 | `00_agent_foundations.ipynb` | Shared pattern: provider, prompts, schemas, retry, failure policy, testing | Exists |
| 01 | `01_post_call_analysis_agent.ipynb` | Post-call summary: transcript → analysis → follow-up date; plus a proposed lead-aware upgrade | Exists (+ proposal) |
| 02 | `02_live_suggestion_agent.ipynb` | Live in-call coaching: intent gate, single-flight worker, never-break contract; plus a proposed lead card | Exists (+ proposal) |
| 03 | `03_lead_research_agent.ipynb` | Lead research: SSRF-safe collectors, evidence, grounded brief, background job | **Planned** (prototype of `LEAD_RESEARCH_AGENT_PLAN.md`) |

Read them in order. Each notebook ends with exercises and a table pointing at the real files.

## Running on Google Colab

1. Open [colab.research.google.com](https://colab.research.google.com), then **File → Upload notebook** and pick a `.ipynb` file
   from this folder (or push the repo and use **File → Open notebook → GitHub**).
2. **Runtime → Run all.** With no key, the notebook prints `MODE: FAKE (offline)`: outputs are canned or rule-based, **not**
   produced by a model, but every step of the flow really executes.
3. To use a real model, add a secret in the left sidebar (key icon), enable *Notebook access*, then re-run:
   - `GROQ_API_KEY` (preferred; the repo's default provider), or
   - `OPENAI_API_KEY`

   Model names (`openai/gpt-oss-120b`, `gpt-4o`, ...) are copied from `backend/app/config.py` in the shared setup cell. Change
   them there if your account uses different ones.

## Notes

- Notebook 03 uses only reserved `.example` domains for its fixtures, so it never touches a real company site. Its optional live
  section (`USE_LIVE = True`) fetches real pages: use it only on business sites you have a legitimate reason to research.
- The "shared setup" cell is identical in all four notebooks (a trimmed copy of `backend/app/ai/providers/`), so each notebook runs on its own.
- Each notebook's closing "Where this lives in the repo" table names real files; keep it in sync if the code moves.
