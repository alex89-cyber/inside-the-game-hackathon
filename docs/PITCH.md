# Pitch

The submission text for the Inside the Game hackathon, kept next to the code so judges can read it with the README.

- Live demo: https://itg-second-screen.blackdesert-df352da7.canadacentral.azurecontainerapps.io
- Challenge: The Synthetic Match Insights Engine

## Second Screen: a multi-agent live match room

**Tagline:** A crew of AI agents watches a synthetic match with you, explains why each moment matters, and tells the story your way: analyst, casual fan, kid or player-focused, in eight languages.

**What it is.** A synthetic football match streams live, event by event. A crew of five agents turns the raw events into stats, decides which moments matter, explains them with the numbers behind them, writes commentary and recaps, and personalizes everything for each viewer. The result drives timed overlay cues on a live 2D pitch in a second-screen web app.

**The problem.** Broadcasts show the same graphics to everyone. Analysts want PPDA and field tilt, casual fans want the story, kids want excitement, and fans of one player want that player. Producing all of that live, in many languages, by hand, does not scale.

**How it works (Ingest → Interpret → Explain → Render → Personalize).**
- **Ingest:** our own match simulator plays 90 minutes one on-ball action at a time (passes, carries, sprints, pressure, tackles, shots, cards) with x/y coordinates, team tactics and momentum swings. The dataset is open in the repo.
- **Interpret:** an Analyst agent keeps live match state (possession, xG, PPDA, field tilt, sprint speeds, pass difficulty) and detects moments: goals, big chances, momentum shifts, pressing spells, control vs chaos, line-breaking passes, speed tags.
- **Explain:** an Explainer agent on Microsoft Foundry (gpt-4.1-mini) says why the moment matters, citing evidence. Every number it writes is checked against the data. An invented number gets one retry with feedback, then a grounded fallback, so the broadcast never shows a made-up stat.
- **Render:** a Director agent turns each insight into a machine-readable overlay cue (timing, layout, colours, stat chips) that the web app draws on the pitch.
- **Personalize:** a Personalizer agent decides whether a moment is worth showing to each viewer and rewrites it for their mode, language, favourite club and favourite player. A Narrator agent writes live commentary and half-time and full-time recaps.

**Microsoft technology.**
- Microsoft Foundry / Azure OpenAI: gpt-4.1-mini, Global Standard, powering the Explainer, Narrator and Personalizer agents
- Azure Container Apps: hosts the live web app, with the model key stored as a Container Apps secret
- GitHub Actions: CI on every push, plus a container image build published to GHCR
- GitHub Copilot: code review on the pull requests in this repository

**Why it is deployable.** The agents run in the background while the pitch keeps playing; overlay cues land a median 4.5 s after the moment. If the model is unreachable, every agent falls back to grounded templates, so the screen never goes blank. One full match with three viewer profiles cost about 105K tokens. An Agents tab shows every handoff, so producers can audit where each insight came from.

**Built by:** Alejandro Bonilla (solo).
