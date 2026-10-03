# Experiment Definition — method

- Ground the hypothesis, baselines and traffic in the user's input or the provided context; cite labels
  (`S1`…) in `citations`. Design choices carry a one-sentence `rationale`.
- Choose the lightest method that can answer the question; an A/B test needs enough traffic — if
  volumes are unknown or low, prefer a qualitative or fake-door test and say why.
- The success threshold and duration are fixed upfront; never "run until significant".
- Guardrails protect users and the business (e.g. error rate, unsubscribe rate, support contacts).
- Never collect more personal data than the test needs; mention consent where users are exposed.
- Do not invent baselines, traffic volumes, dates or results.
- Keep ids short and stable (`hyp-1`, `exp-fake-door`, `m-primary`).
