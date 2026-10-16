# ORION contracts: versions, fixtures and the ORBIT → FORGE → NOVA traversal

NOVA reads what ORBIT assembled (directly, or through FORGE which prepares the context of a run) and answers FORGE's
runs. Each hop is a wire contract with a versioned fixture and a test that needs **no external service**.

## Protocol compatibility matrix

| Contract | Producer → reader | Version | Introduced | Content | Readers accept |
|---|---|---|---|---|---|
| ORBIT context package and snapshot (`schema_version`) | ORBIT → FORGE, NOVA | **1** (implicit) | before NOV-73 | `items[]` (`excerpt`, `classification`, ids, `citation`, `version`, `uri`…), snapshot items with `forgotten` | a payload **without** `schema_version` is read as 1 |
| | | **2** (current) | NOV-73 | adds `schema_version`, `max_classification`, `items[].access_scope`, `SnapshotItem.classification` | FORGE and NOVA read 1 and 2 |
| FORGE Agent Protocol request (`protocol`) | FORGE → NOVA | **`forge-agent-protocol/v1`** | FAP v1 | `input`, `context.documents[]`, `constraints`, `agent`, `budget`, `nova_agent_id` | NOVA ignores unknown keys |
| | | v1 + classification extension | NOV-68, NOV-69 | `context.documents[].classification`, `context.max_classification`, `context.orbit_context`, `documents[].citation/version/document_id` | a document without level is C3 |
| FORGE Agent Protocol response | NOVA → FORGE | **`forge-agent-protocol/v1`** | FAP v1 | `output`, `output_json`, `events[]`, `usage`, `model`, `metadata`, `error` | FORGE ignores unknown keys |
| | | v1 + version extension | NOV-72 | `metadata.requested_version`, `executed_version`, `executed`, `accepted_overrides`; HTTP 422 `unsupported_override` (`error.fields`) | |

Error vocabulary NOVA returns to FORGE: 401 `UNAUTHORIZED` (bad credential), 404 `NOT_FOUND`, 400 `EXECUTION_ERROR`,
403 `CLASSIFICATION_REFUSED` (context above NOVA's ceiling), 422 `unsupported_override`, 200 with `TIMEOUT`.

Rules every producer follows:

* **Additive only**: a key is never renamed or removed inside a version; readers ignore unknown keys.
* **A new version is a decision**: bump the version, update the table above and the frozen key lists in ORBIT's
  `tests/test_contract_fixtures.py`, regenerate the fixtures and refresh the copies (see below).
* Neither `schema_version` nor `protocol` is rejected at run time today (a reader accepts what it can read); the contract
  tests are the guard, not a runtime check.

## Fixtures: one source per contract, verified copies elsewhere

| Fixture set | Source of truth (repository) | Verified copies |
|---|---|---|
| ORBIT `ContextPackage` / `Snapshot` (real context, limited rights, C3, forgotten item) | ORBIT `contracts/orbit/`, written by `backend/scripts/export_contract_fixtures.py` from the real schemas | FORGE `backend/tests/fixtures/orbit/`, NOVA `tests/fixtures/orbit/` |
| FAP request bodies produced by FORGE from those ORBIT answers | FORGE `contracts/fap_request/`, written by `backend/scripts/generate_fap_fixtures.py` from the real FORGE code | NOVA `tests/fixtures/fap_request/` |
| FAP responses of NOVA (200, 401, 403, 422) | NOVA `contracts/fap_response/`, written by `tests/contract/test_fap_response_fixtures.py` from the real route | FORGE `backend/tests/fixtures/fap_response/` |

Every directory carries a `manifest.json` (sha256 per file; the generated sets also record the manifest hash of the set
they derive from). A copy is the source byte for byte. What fails, and where:

| You change… | …without refreshing | Fails |
|---|---|---|
| an ORBIT schema | the fixtures | ORBIT `test_contract_fixtures.py` (regeneration + frozen keys) |
| a fixture file in a copy | its manifest / the source | `verify_copy` in the repository holding the copy |
| FORGE normalisation or `build_protocol_body` | `contracts/fap_request` | FORGE `tests/contract/test_orbit_to_fap.py` |
| the ORBIT copy of one repository only | the other copies | the `derived_from` hash check (FORGE bodies ↔ ORBIT copy, NOVA responses ↔ request copy) |
| NOVA's route or mapper | `contracts/fap_response` | NOVA `tests/contract` (regeneration + traversal) |

Because a CI sees only its own repository, equality **with the source** is checked with the scripts or the environment
variables below (locally, or in the optional chain job). All of it uses synthetic data (fictitious C2/C3, no secret).

### Refresh procedure (after any contract change)

```bash
# 1. ORBIT (source of the ORBIT contract)
cd ORBIT/backend && uv run python scripts/export_contract_fixtures.py
# 2. FORGE: copy ORBIT, regenerate the request bodies it sends to NOVA
cd FORGE/backend
uv run python scripts/sync_contract_fixtures.py --orbit ../../ORBIT/contracts/orbit
uv run python scripts/generate_fap_fixtures.py
# 3. NOVA: copy ORBIT and FORGE, regenerate its responses
cd NOVA
uv run python scripts/sync_contract_fixtures.py --orbit ../ORBIT/contracts/orbit --fap-request ../FORGE/contracts/fap_request
NOVA_REGENERATE_CONTRACTS=1 uv run pytest tests/contract/test_fap_response_fixtures.py
# 4. FORGE: copy NOVA's responses
cd FORGE/backend && uv run python scripts/sync_contract_fixtures.py --fap-response ../../NOVA/contracts/fap_response
```

Verify equality with the sources (exit code 1 on drift): `sync_contract_fixtures.py … --check`, or run the tests with
`CONTRACT_SOURCE_ORBIT=<ORBIT>/contracts/orbit`, `CONTRACT_SOURCE_FORGE=<FORGE>/contracts/fap_request`,
`CONTRACT_SOURCE_NOVA=<NOVA>/contracts/fap_response` (those tests are skipped when the variable is unset).

## Claims contract (NOV-104, ADR 001 §3-§4)

The access token of the federated identity (realm `orion`, RS256, JWKS) is a wire contract too, and it is tested **before**
any service implements OIDC, with no IdP: signed fixtures plus one self-contained validation module. Nothing here is
wired into a login path; with the defaults the behaviour of every service is unchanged.

| Claim | Contract | Read as |
|---|---|---|
| `iss`, `aud` | exact `iss` of the realm; `aud` ∋ the reader (`nova-web`, `orbit`, `forge`: one token per audience) | refused otherwise |
| `sub`, `exp`, `iat` | mandatory | refused when missing or not a string / number |
| `nbf` | checked **when present** (Keycloak does not emit it by default: deviation from the ADR table, deliberately the safe side) | `not_yet_valid` |
| `email`, `email_verified` | account matching only if `email_verified` is `true` | `email_matchable` |
| `orion_workspace_id` | UUID; **absent: the token opens no workspace resource** (and `orion_project_id` is dropped) | `space_access` |
| `orion_project_id` | UUID; the active project, membership stays local | `project_id` |
| `orion_clearance` | integer 0-3, a ceiling; **present but malformed (`"3"`, `7`, `true`): token refused**, never read as "no cap" | `effective_clearance = min(local, claim)`; absent: the local value |
| `realm_access.roles` | `<service>-<role>`; only the prefix of the reading service counts, lookalikes (`novaadmin`) grant nothing | see below |
| `act` | `{sub, client_id}`; a delegated token lives at most 900 s | `delegated_by` |
| `scope`, `amr` | string (space separated) or list | `scopes`, `mfa` (`amr` ∋ `mfa`) |
| any other claim | ignored | |

Decision per service (what `tests/contract/test_claims_contract.py` executes on every fixture):

| Output | NOVA (`nova-web`) | ORBIT (`orbit`) | FORGE (`forge`) |
|---|---|---|---|
| `platform_admin` | realm role `nova-admin` | realm role `orbit-admin` | capped role is `admin` |
| `role` | local project role, unchanged (no realm role grants one) | local project role, unchanged | local global role **capped** by the highest `forge-*` realm role, never raised; no local account: none; no `forge-*` role: the local role |
| `effective_clearance` | `min(local, orion_clearance)`; `local` = linked ORBIT clearance or `DEFAULT_CLEARANCE` | `min(User.clearance, claim)` | `min(local, claim)` |
| `space_access` | `orion_workspace_id` present | idem | idem |

Decision on an ambiguity (the most prudent reading): the ADR says a FORGE `forge-admin` realm role maps to `admin` and
also that the effective role is the local one capped by the realm role. The module applies the cap, so `forge-admin` in
the realm does not make a local `maintainer` an `admin`; the provisioning of a first role (no local account) is a decision
of the FORGE OIDC ticket (ADR §8: linking needs the user's confirmation).

### Files

| What | Source (NOVA) | Copy in ORBIT / FORGE |
|---|---|---|
| validation module (standard library only, one file) | `nova/domain/orion_claims.py` | same bytes, any path (`MODULE_PATH` in the test) |
| signed fixtures, public JWKS, context (issuer, clock), manifest | `contracts/claims/` (`case_*.json`, `jwks.json`, `context.json`, `manifest.json`) | `contracts/claims/` byte for byte |
| generator | `scripts/generate_claims_fixtures.py` | not copied |
| portable test | `tests/contract/test_claims_contract.py` | copied; set `SERVICES` to the repository's service and the three paths |

`manifest.json` records the sha256 of every fixture **and of the module** (`module.sha256`) and the list of contract claims.
No key is committed: the generator creates a throw-away RSA key at each run, signs, keeps the public key only, and replays
its own hand-written table through the module before finishing (`--check` replays what is committed). A regeneration
changes every token: it is a contract decision, followed by refreshing both copies:

```bash
cd NOVA && uv run python scripts/generate_claims_fixtures.py        # then: uv run pytest tests/contract
cp NOVA/nova/domain/orion_claims.py <ORBIT or FORGE>/<module path>
rm -rf <ORBIT or FORGE>/contracts/claims && cp -R NOVA/contracts/claims <ORBIT or FORGE>/contracts/claims
cp NOVA/tests/contract/test_claims_contract.py <ORBIT or FORGE>/tests/contract/   # then edit SERVICES / paths once
```

| You change… | …without refreshing | Fails |
|---|---|---|
| a claim removed or renamed in a fixture (or in the token an IdP issues) | the table | the signature (`bad_signature`) and the manifest hash; the decision changes (`test_claims_source.py` mutates each claim) |
| the module | the manifest and the copies | `test_fixtures_and_module_match_the_manifest` in each repository |
| a fixture in a copy | the source | the manifest hash |
| the table of ADR §4 | the fixtures' `expect` | `test_decision_matches_the_adr_table` |

## Traversal test (`tests/contract/`, part of the default `testpaths`)

`test_orbit_forge_nova_traversal.py` chains the three fixtures: the real ORBIT answer, the body FORGE produced from it,
then NOVA's `NovaRunRequest` / `mapper.provided_context` and the real `POST /v1/agents/{id}/runs` route (in-process,
SQLite, scripted LLM). Scenarios: real context, limited rights, C3 document, forgotten item, wrong credential (401),
version change (422 `unsupported_override`, nothing executed). Checked at each step: the excerpt is identical and not
empty, a C3 document stays C3 (and nothing is lowered), the source stays identifiable (`ref_id`, `document_id`,
`version`, title, `[source: <id>]` in the output), a `forgotten` item never reaches NOVA, a C1-only reader never gets a C3
level. Mutation checks done when the tests were written: editing a copy, the mapper, the declared maximum or the response
shape each fails the suite.

The existing opt-in test against a real FORGE (`tests/cross_instance`, `NOVA_E2E_FORGE_URL` / `NOVA_E2E_FORGE_KEY`) is kept
and is not part of the default run.

## Optional chain job (not enabled)

A manual job can run the whole chain at **pinned commits**. It is documented here and **not** committed as a workflow:
it can only be validated by running it on GitHub, and it must not run automatically before the production freeze ends.
The three repositories are public, so no secret and no token are needed. Design:

* trigger `workflow_dispatch` only, with inputs `orbit_sha`, `forge_sha`, `nova_sha` (full commit SHAs, never branch
  names); `permissions: contents: read`; never `push` or `pull_request`; no deployment step, no remote URL;
* step 1, contract chain (no service, a few minutes): check out the three repositories side by side at the pinned SHAs;
  run ORBIT `export_contract_fixtures.py --check`, FORGE `generate_fap_fixtures.py --check`, `sync_contract_fixtures.py
  --orbit --fap-response --check`, NOVA `sync_contract_fixtures.py --orbit --fap-request --check`, then each repository's
  `tests/contract` with the three `CONTRACT_SOURCE_*` variables set;
* step 2, three real backends: start the services of each `docker-compose.yml` on throw-away databases (ORBIT 5433 /
  9201 / 6380, FORGE 5434 / 6381, NOVA SQLite), run the ORBIT and FORGE API (and the FORGE worker), create a FORGE admin
  key from its bootstrap admin, then `NOVA_E2E_FORGE_URL=… NOVA_E2E_FORGE_KEY=… pytest tests/cross_instance`; upload the
  logs as an artifact on failure;
* both steps use throw-away data only and the workflow is run by hand when a contract changes or before a release.

```yaml
# Sketch only (docs, not .github/workflows): `on: workflow_dispatch` with the three SHA inputs,
# actions/checkout x3 with `repository`, `ref: ${{ inputs.<repo>_sha }}` and `path: <repo>`, then the commands above.
```
