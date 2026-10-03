# Artifact editing — method

The CURRENT SECTIONS of the Artifact are given as JSON. Rewrite only the requested sections.
- Apply the user's instruction precisely; do not change tone or structure elsewhere.
- Keep existing `id`s for items that remain; drop items only when the instruction implies it.
- Keep citations that still support the content; add citations only with labels from the provided
  context.
- The sections to return are generic: the engine sets the actual section keys and schema at runtime from
  the target Artifact type (this Skill's declared `fills` is a placeholder for validation).
