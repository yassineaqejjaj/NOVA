# RICE Prioritization — method

- Take candidates and the data behind estimates (usage, segment sizes, estimates) from the user's input
  or the provided context; cite labels (`S1`…) in `citations` on the items they inform.
- Use the standard scales exactly; do not invent intermediate impact values.
- Compute the score arithmetically and check it: reach 2000, impact 1, confidence 0.8, effort 4 → 400.
- When reach or effort is guessed, lower confidence accordingly and record the guess as an assumption.
- Never invent usage figures or estimates presented as facts; state the basis of each estimate.
- The `rationale` of each item explains its rank in one sentence.
- Keep item ids stable and reuse the ids or keys of candidates found in context.
