# Global preference implementation handoff

## Contract

`/codex_accounts n` / `select n` explicitly persist chosen stable ID at priority 0 for the owning profile. `Active` denotes persisted global preference, NOT the credential of an existing runtime/request. Commands and Telegram buttons share authorization and mutation logic. No execution middleware or process-local pin remains.

## Installed API investigation

Inspected installed `hermes_cli.auth` and `agent.credential_pool` through `inspect.getsource` using the host Python interpreter. `CredentialPool.move_entry(id, 0)` reorders entries, normalizes priorities and persists; it does not rebind other pool instances or SDK clients. `hermes_cli.auth` has no move/reorder wrapper. Its existing `read_credential_pool` and `write_credential_pool` merge boundary supports the same Codex priority update under `_auth_store_lock` without `load_pool` seeding/normalizing or dataclass metadata loss. The plugin uses this boundary, retains current token generations, and reads back the exact target/order/all row fields before reporting success. Borrowed/global-root credentials are refused in a different owning profile.

Future pool loading sees the preference, subject to strategy, availability, cooldown and quota. Existing runtimes/sessions and in-flight requests may retain prior credentials. Forced immediate global switching is not claimed. A newly loaded runtime is required to reliably consume the persisted preference; the plugin does not restart anything.

## Verification

New focused tests were run RED (7 expected failures), then GREEN (7 passing). Full suite with Telegram SDK isolated from the host installation:

- 45 tests executed: **45 passed**.
- `tests/test_runtime_identity_seam.py` retains its valid SDK wire-identity counterexample and now checks the revised UI contract: `[Active]` marks the persisted global preference, not the SDK credential already bound to an existing runtime.
- `git diff --check` passes (Git emitted only safe.directory/CRLF warnings).
- `test_global_selection.py` uses OpenAI SDK MockTransport to show that an existing client retains fake-token-one after the persisted preference changes to account two.
- Independent review: **APPROVE**; no blocking correctness/security findings. Reviewer verified profile ownership, auth-store lock, token preservation, readback, and future-preference semantics.

No core changes, actual account selection, real pool writes, OAuth/reset action, deployment, installation or publication were performed. Source inspection and synthetic temporary auth stores were used. Historical POOL_IDENTITY_FINDINGS/RUNTIME_IDENTITY_BLOCKER documents describe the earlier runtime-identity investigation; this note records the clarified global-preference contract.
