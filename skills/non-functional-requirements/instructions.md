# Non-Functional Requirements — method

Only the non-functional section is written; the rest of the requirements document stays untouched.
- Take SLAs, policies, standards and load figures from the provided context and cite labels (`S1`…) in
  `citations`. A target you propose carries a `rationale` saying it is a proposal to confirm.
- Every requirement is measurable and testable: metric, threshold, conditions (load, percentile, data
  volume, device). "The app must be fast" is rejected.
- Pick categories that matter for this scope (e.g. privacy when personal data is processed, accessibility
  for user-facing UI) rather than a generic list.
- Never invent compliance obligations or certifications; mention them only when context states them.
- Keep existing requirement ids; new ids follow the pattern `nfr-perf-1`, `nfr-a11y-1`.
