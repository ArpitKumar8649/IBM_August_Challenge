# Phase 0 — Prep Checklist (Jul 24 – Jul 31, 2026)

> **No project code before Aug 1** — project creation opens at launch. Everything here is accounts, learning, team, and domain knowledge.
> Status: 🟢 done · 🟡 in progress · ⬜ not started

## 0. Environment — verified ✅ (2026-07-24)

| Item | Status |
|------|--------|
| Python 3.12.1, pip 26.0.1, Node v24.14.0, npm 11.9.0, git 2.53.0 | ✅ |
| CelesTrak GP endpoint (no auth) | ✅ reachable |
| NASA DONKI (free key; `DEMO_KEY` works for testing) | ✅ reachable |
| NOAA SWPC Kp forecast (no auth) | ✅ reachable |
| Space-Track.org | ✅ reachable |
| IBM Cloud, PyPI | ✅ reachable |
| **Space-Track auth** (login + SATCAT + CDM_PUBLIC) | ✅ verified 2026-07-24 — pace queries ~2 s apart |
| **NASA DONKI key** | ✅ verified 2026-07-24 — returns real storm notifications |
| **watsonx.ai → Granite 4** (`ibm/granite-4-h-small`) | ✅ verified 2026-07-24 — **tool calling confirmed**; use `/ml/v1/text/chat` |
| numpy / scipy / sgp4 / fastapi / langchain | ⬜ install Aug 1 (`pip install numpy scipy sgp4 fastapi uvicorn httpx apscheduler pydantic langchain langchain-ibm langgraph`) |

## 1. Accounts & access (USER)

| # | Task | Status | Notes |
|---|------|--------|-------|
| 1.1 | **Register Space-Track.org** — https://www.space-track.org/auth/createAccount | ✅ | Verified 2026-07-24: login, SATCAT, and CDM_PUBLIC all return data. ⚠️ Pace queries ~2 s apart or sessions drop. Limits: ~300 q/min, ~3,000 q/day. |
| 1.2 | **IBM Bob** — download the standalone IDE from https://bob.ibm.com/download (⚠️ it is NOT a VS Code extension — it's its own IDE + terminal "Bob Shell"). Full guide: `docs/IBM_BOB_GUIDE.md` | ⬜ | Install now; do a 5-min sign-in verification (IBMid login, 40 Bobcoins/30-day trial). **Re-sign-in Aug 1** so the 30-day clock covers the build window (or create a fresh trial account per the FAQ guide if it expires). |
| 1.3 | **NASA API key** — https://api.nasa.gov (free, instant) | ✅ | Verified 2026-07-24 — returns real DONKI geomagnetic-storm notifications. |
| 1.4 | **IBM Cloud free-tier account** — https://cloud.ibm.com/registration | 🟡 | watsonx.ai ✅ verified 2026-07-24 (Granite 4 `ibm/granite-4-h-small`, tool calling works). **Code Engine access still to confirm** (catalog → search "Code Engine"). |
| 1.5 | **Join challenge Discord** — link on the challenge platform | ⬜ | Watch `#august-challenge-and-learning`. |

## 2. Required learning (USER) — submission artifact

| # | Task | Status |
|---|------|--------|
| 2.1 | Complete the required IBM SkillsBuild learning activity ("Troubleshoot Your Code Using IBM Bob" and/or "How IBM Bob and AI Tools Are Changing the Way Solutions Are Built") | ⬜ |
| 2.2 | **Save the completion certificate** (screenshot + PDF) into a shared folder — it's evidence for submission | ⬜ |

## 3. "Hello Granite" smoke test (USER) — practice only, no project code

Once the IBM Cloud account is ready (~30–45 min):

1. In watsonx.ai → **Prompt Lab**, pick a Granite model (e.g. `ibm/granite-3-3-8b-instruct` or the newest Granite 4 available). Send one chat message. Confirm tokens aren't blocked by the free tier.
2. Get an API key: IBM Cloud console → **IAM → API keys** → create one.
3. On Aug 1 (or now, as a throwaway script outside this repo):
   ```bash
   pip install langchain-ibm
   WATSONX_APIKEY=<your-key> python - <<'EOF'
   from langchain_ibm import ChatWatsonx
   llm = ChatWatsonx(model_id="ibm/granite-3-3-8b-instruct",
                     url="https://us-south.ml.cloud.ibm.com",
                     project_id="<your-project-id>")  # create a watsonx project first
   print(llm.invoke("Reply with exactly: hello granite"))
   EOF
   ```
4. Note in `docs/BOB_LOG.md` which region/model worked (us-south vs eu-de etc.).

## 4. Team & design partner (USER)

| # | Task | Status |
|---|------|--------|
| 4.1 | Attend **Aug 5, 10 AM ET team-formation webinar**; recruit 2–4 people | ⬜ |
| 4.2 | Assign roles: engine · agent/backend · frontend · demo/README/validation (overlap fine) | ⬜ |
| 4.3 | **Design-partner outreach — start NOW** (needs lead time). Use `docs/OUTREACH_TEMPLATE.md`; target 3–5 university CubeSat teams | ⬜ |

## 5. Domain reading (USER) — `docs/READING_LIST.md`

Skim all 8 sections; the summaries are inline so 2–3 hours total suffices. Pay special attention to §3 (collision probability formula) and §7 (competitive landscape — your differentiation story). Status: ⬜

## 6. Verify open questions on Discord / FAQ guide (USER)

- [ ] Prize amounts
- [ ] Eligibility (age, country, student status)
- [ ] **Team-size limits**
- [ ] Judging-criteria weights
- [ ] **Must all code be written inside the Aug 1–31 window?** (affects what prep can include)
- [ ] IP/licensing terms
- [ ] Exact submission-platform mechanics

## 7. Aug 1 launch sequence (first 2 hours)

1. Create the project page on the challenge platform (opens at launch)
2. `pip install numpy scipy sgp4 fastapi uvicorn httpx apscheduler pydantic langchain langchain-ibm langgraph`
3. Scaffold the repo per `ORBITWARDEN_IMPLEMENTATION_PLAN.md` §1 (license + CI + README sections already exist — fill in the structure)
4. Task 1.2 of the plan: `engine/ingest/celestrak.py`
5. Log everything in `docs/BOB_LOG.md`
