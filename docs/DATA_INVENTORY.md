# Copies of ORBIT context kept by NOVA, and their retention

Technical scoping of what NOVA stores when ORBIT serves it context, and what happens to each copy. It is **not** a legal
compliance conclusion. Retention is applied by the daily `retention` job (`nova/services/maintenance.py`); an
erasure by source, project or user (`nova/services/forget.py`) goes further, at once.

| Copy | Where | What it holds | Routine retention | On forget |
|---|---|---|---|---|
| Retrieval references | `context_retrieval_references` | items served (title, short excerpt, ids, level), the retrieval query | `NOVA_CONTEXT_REFERENCE_RETENTION_DAYS` (180 d), rows deleted | items removed (source) or rows deleted (project, user); query blanked; marked revoked |
| LangGraph checkpoints | `checkpoints`, `checkpoint_blobs`, `checkpoint_writes` (Postgres; memory in tests) | the whole run state: context items, step outputs, drafts | `NOVA_CHECKPOINT_RETENTION_DAYS` (90 d after the run ended), thread deleted | thread deleted for every run that held the source |
| Conversation blocks | `message_blocks` (`context_sources`, citations) | sources shown to the user (title, excerpt) | kept with the conversation | items scrubbed, block marked `forgotten` |
| Event stream | `execution_events` | block events (same as above), progress | `NOVA_EXECUTION_EVENT_RETENTION_DAYS` (90 d) | items scrubbed |
| Tool outputs | `tool_executions.output` | what a retrieval tool returned (redacted) | kept | output emptied |
| Run input | `tasks.input` | `provided_context` (FORGE-driven runs), pinned references | kept | items scrubbed, pins removed, `forgotten_at` set: no replay with the original context |
| Skill outputs | `skill_executions.output` | derived content of a step | kept | emptied under `NOVA_FORGET_ARTIFACTS=purge` |
| Derived Artifacts | `artifacts`, `artifact_versions`, `artifact_comments` | content written from the sources | kept (user content) | flagged "source removed" (`mark`, default) or deleted (`purge`) |
| FORGE capture outbox | `forge_outbox.payload` | the run record waiting to be sent to FORGE (context items) | emptied once settled | emptied, a waiting capture is cancelled (`skipped`) and never sent |
| FORGE evaluations | `integration_references` (kind `evaluation`), and FORGE's own run | run id, scores; FORGE holds the captured run | kept | link deleted, a `forge_erasure_requests` row asks FORGE to delete the run (`DELETE /api/v1/runs/{id}`, acknowledged by a 2xx, retried every 10 min) |
| ORBIT events and forget requests | `orbit_events`, `forget_requests`, `audit_events` | ids, types, counts of what was done | kept (audit trail) | never hold content |

Not copies of ORBIT content, so not erased: users' own requests (`tasks.objective`, conversation text), `llm_calls`
(tokens, cost), the run manifest (counters and ids).

**Triggers.** A signed ORBIT `document.forgotten` / `memory.forgotten` event (`docs/OPERATIONS.md`) erases the source at
once; an administrator can erase by source, project or user (`POST /api/v1/admin/forget`, history on
`GET /api/v1/admin/forget`). ACL or classification changes only revoke the extracts (they are not re-served) and flag the
Artifacts.

**Metric.** `nova_forget_purged_total{kind}` (OpenTelemetry) counts what was erased by kind; the retention job returns
its counts (`context_references`, `execution_events`, `checkpoints`).

**Known limits.** The FORGE side of an erasure depends on FORGE offering the endpoint (its retention work is tracked
separately): until it does, the request stays `pending` (visible, retried) and the link on NOVA's side is already gone.
Backups of the database are not rewritten. A partial request (`status: partial`) must be repeated.
