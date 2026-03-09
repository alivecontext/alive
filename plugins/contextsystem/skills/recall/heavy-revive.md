# Heavy Revive

Five parallel agents reconstruct a session transcript. Each extracts one dimension. The goal is full awareness transplant — after absorbing all five outputs, the current squirrel has the same level of awareness as the one that ran the original session.

---

## Dispatch

Receive `{transcript_path}` from the recall skill. Dispatch all five agents as parallel Agent tool calls with `subagent_type: "general-purpose"`. Each prompt = shared preamble + agent-specific instructions, with `{transcript_path}` substituted.

---

## Shared Preamble

Prepend to every agent prompt:

```
You are one of five agents reconstructing a previous work session. Your job is NOT to
summarise — it is to RECONSTRUCT. The goal is that the squirrel reading your output
absorbs enough of the original session's substance that it has the same level of
awareness as the squirrel that ran it.

Read the JSONL transcript at: {transcript_path}

The transcript is JSONL — one JSON object per line. Each line has a "type" field
(user, assistant, tool_use, tool_result, progress, file-history-snapshot, etc.)
and typically a "message" field with content. Focus on "user" and "assistant" types
for the conversation, and "tool_use"/"tool_result" for understanding what work was done.

Read the ENTIRE transcript. Do not stop early. Do not skip sections.

You are extracting ONE specific dimension (described below). Other agents are handling
the other dimensions — stay focused on yours. Go deep, not wide.
```

---

## Agent 1: Narrative & Energy

```
{shared preamble}

YOUR DIMENSION: Narrative & Energy

Reconstruct the arc of the session — not what happened (another agent covers that),
but HOW it felt. You are mapping the emotional and creative topology.

Extract and describe:

1. **Session phases** — break the session into natural phases based on energy shifts.
   Name each phase. "Phase 1: Slow start, getting oriented" / "Phase 3: Locked in,
   shipping fast."

2. **Flow states** — identify moments where the human and squirrel were locked in
   together. What were they working on? What made it click? How long did it last?
   What broke the flow?

3. **Creative breakthroughs** — moments where an idea crystallised, a framing landed,
   or something new emerged that wasn't there before. Describe what the breakthrough
   was and the exchange that produced it.

4. **Excitement signals** — what did the human get excited about? Look for:
   exclamation marks, rapid follow-up messages, "yes!", "that's it", "love it",
   building on ideas quickly, energy spikes in message frequency.

5. **Frustration or drag** — where did things stall? What caused friction? Long gaps
   between messages? Repeated attempts at the same thing? Explicit frustration?
   Tool errors that broke momentum?

6. **The dynamic** — how did the human and squirrel relate in this session?
   Was it directive (human leading, squirrel executing)? Collaborative (thinking
   together)? Was the squirrel proactive or reactive? Did the dynamic shift?

7. **Momentum shifts** — what caused energy to go up or down? A successful test?
   A surprising result? A blocker? An interruption?

Write in prose, not bullets. You're painting the picture of what this session felt like
to be in. Someone reading your output should understand the VIBE — not just the topics.
```

## Agent 2: Decisions & Reasoning

```
{shared preamble}

YOUR DIMENSION: Decisions & Reasoning

Extract EVERY decision made during this session, with full reasoning chains.

For each decision, capture:

1. **The decision** — what was decided, stated clearly
2. **The trigger** — what prompted this decision (a question, a problem, a discovery)
3. **Alternatives considered** — what other options were on the table
4. **Why this choice** — the specific reasoning, constraints, or preferences that
   drove the decision
5. **Why NOT the alternatives** — what was wrong with or less ideal about the other
   options
6. **Who decided** — did the human decide, did the squirrel recommend and the
   human approve, or was it implicit?

Also capture:
- **Principles established** — rules or patterns decided that should carry forward.
  "We're doing X this way because Y" statements that apply beyond this one instance.
- **Pivots** — moments where the approach fundamentally changed. What was the old
  approach? What triggered the change? What was the new approach?
- **Constraints discovered** — limitations found during the session that shaped
  decisions (technical limits, API behaviour, time pressure, dependencies).
- **Preferences expressed** — things the human explicitly or implicitly preferred
  (style, approach, tooling, naming, architecture patterns).

Format as a numbered list of decisions in chronological order. Each decision gets a
small block with the fields above. Don't merge decisions — keep them atomic. If 15
decisions were made, list all 15.
```

## Agent 3: Quotes & Moments

```
{shared preamble}

YOUR DIMENSION: Quotes & Moments

Capture the session's DNA through verbatim quotes and defining moments.

You are looking for lines that, if read, make you feel like you were in the room.
The sharp framings. The breakthrough articulations. The moments of clarity.

Extract:

1. **Human quotes** — things the human said that were:
   - Sharp or memorable articulations of what they want
   - Strong opinions or preferences expressed with conviction
   - Moments of clarity where they nailed a concept
   - Frustrations that reveal what matters to them
   - Excitement that shows what they care about
   - Corrections or redirections that reveal how they think

2. **Squirrel quotes** — things the agent said that the human responded well to:
   - Framings that landed (the human built on them, agreed, or got excited)
   - Explanations that clearly worked (no follow-up confusion)
   - Proposals that were accepted enthusiastically
   - Analogies or metaphors that stuck

3. **Exchange moments** — back-and-forth sequences (2-4 messages) where something
   clicked. The human said X, the squirrel said Y, the human said "yes
   exactly" — that whole exchange, quoted.

4. **Turning points** — the single message or exchange that changed the direction
   of the session. Quote it verbatim.

Format each quote as:

> "exact quote here"
> — human/squirrel

For exchange moments, show the full sequence:

> **human:** "message"
> **squirrel:** "response"
> **human:** "reaction"

Include at minimum 10 quotes if the session is substantial. Don't paraphrase.
Don't clean up grammar or typos in human quotes — preserve them exactly.
The imperfections are part of the voice.
```

## Agent 4: Technical Substance

```
{shared preamble}

YOUR DIMENSION: Technical Substance

Map everything that was built, modified, discovered, or established technically.

Extract:

1. **Files created** — full absolute paths, what each file contains, why it was
   created, and its current state (complete? draft? placeholder?).

2. **Files modified** — full absolute paths, what changed (not "updated config" —
   WHAT in the config changed and WHY), the before/after if discernible from
   tool_use entries.

3. **Files read** — significant files that were read for context (from Read/Glob/Grep
   tool calls). These tell the next session what reference material matters.

4. **Architecture decisions** — structural choices about how things are organised,
   connected, or built. What patterns were established? What conventions were set?

5. **Code patterns** — specific technical patterns used or established. Framework
   choices, naming conventions, API patterns, data structures.

6. **Commands run** — significant Bash commands and their results, especially:
   - Install/setup commands
   - Test runs and their results
   - Build commands
   - API calls or curl commands
   - Git operations

7. **Dead ends** — technical approaches attempted and abandoned. What was tried,
   what happened, why it was abandoned. This prevents the next session from
   repeating mistakes.

8. **Dependencies and integrations** — external services, APIs, packages, or tools
   that the work depends on. Version numbers if mentioned.

9. **What to read** — an ordered list of files the next session should read to get
   up to speed on the technical state. Most important first.

Format with clear headers for each category. Use full paths everywhere.
Don't abbreviate or truncate file paths.
```

## Agent 5: Open Threads

```
{shared preamble}

YOUR DIMENSION: Open Threads

Find everything unfinished, unresolved, or forward-looking. Your job is to make sure
NOTHING falls through the cracks between sessions.

Extract:

1. **Unfinished work** — things that were started but not completed. For each:
   - What was the task?
   - How far did it get? (percentage, last step completed, what remains)
   - Where did it stop? (what file, what line of thinking, what blocker)
   - What's needed to complete it?

2. **Open questions** — questions that were raised during the session but never
   answered or resolved. Include questions asked by either the human or the
   squirrel. Note the context — why was this question raised?

3. **Promised but not delivered** — things the squirrel said it would do, or the
   human said they wanted, that weren't done by session end.

4. **Dependencies and blockers** — things that can't proceed until something else
   happens. What's blocked? What's blocking it? Is the blocker internal (just
   needs work) or external (waiting on someone/something)?

5. **Deferred items** — things explicitly pushed to "later" or "next session."
   Quote the moment of deferral so the context is clear.

6. **Fragile context** — information that was discussed in conversation but never
   written to any file. If the transcript were lost, this information would be
   gone. Flag it clearly.

7. **Implied next steps** — things that logically follow from the work done, even
   if nobody explicitly said "next we should..." Look at the trajectory and
   identify what the next session will probably need to do.

Format as a structured list. Each item should have enough detail that someone
could act on it without reading the transcript. If an item references a file,
include the full path. If it references a conversation, quote the relevant
exchange.
```

---

## Output Presentation

Present results in bordered blocks in this order. If agents return out of order, buffer and present in sequence.

```
╭─ 🐿️ revive — narrative & energy
│  [agent 1 output]
╰─

╭─ 🐿️ revive — decisions & reasoning
│  [agent 2 output]
╰─

╭─ 🐿️ revive — quotes & moments
│  [agent 3 output]
╰─

╭─ 🐿️ revive — technical substance
│  [agent 4 output]
╰─

╭─ 🐿️ revive — open threads
│  [agent 5 output]
╰─
```

---

## Synthesis

After all five dimension blocks are presented, close with a `╭─ 🐿️ revive — summary` block. Written by the squirrel directly — no extra agent. Distil the five outputs into a concise briefing that captures what happened, where things stand, and what comes next. Keep it short. The dimension blocks are the depth; the summary is the landing.
