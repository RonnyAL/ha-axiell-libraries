# Account-scoped renewal authorization

The owner requests non-admin household renewal without weakening account
isolation. This corrects the earlier admin-only policy; it changes no Solus
protocol, renewal/confirmation manager, session, entity or action signature.

## Root cause and approach

`services.py` registers through `async_register_admin_service`, whose Core wrapper
raises Unauthorized for every known non-admin before the handler runs. The
existing non-admin test uses a read-only user, so it never demonstrates that a
regular user with control permission should succeed.

Home Assistant currently authorizes entities, not config entries. Use normal
`hass.services.async_register` and an explicit server-side permission check for
the selected entry. Require `POLICY_CONTROL` on at least one entity whose
registry `config_entry_id` is the selected ID and whose platform is
`axiell_libraries`. Read permission alone is insufficient. Check current registry
membership and permissions on every invocation, including every confirmation.

Alternatives considered: plain registration alone would expose every account;
Core's `verify_domain_control` checks any entity across the integration and could
let access to one account authorize another; a separate integration ACL or a
hardcoded single sensor would add configuration or entity-name dependencies.
The chosen scoped check follows Core's entity permission model while retaining
the existing config-entry action signature. This is an implementation choice
under the owner's request to select an appropriate authorization model.

## Contract

- Resolve `call.context.user_id` using `hass.auth.async_get_user`. Unknown users
  (including an empty supplied ID) raise `UnknownUser`; inactive users raise
  `Unauthorized`, before coordinator calls or provider I/O.
- Exactly `user_id is None` retains HA's existing trusted internal/system call
  behavior. No caller-provided user identity, permission flag or target entity
  field is introduced. Authenticated frontend calls carry their server-provided
  HA context; frontend visibility/is_admin checks are not authorization.
- For user calls, reject when no matching registered Axiell entity grants
  control. Filter by selected entry and platform before checking permission.
  Use native HA Unauthorized errors with the call context and control permission;
  never add account data or provider credentials to error text.
- Authorize before account resolution/confirmation processing. Then retain
  existing Core loaded-entry/domain validation and the existing coordinator call.
  Unauthorized callers must not read/refresh loans, write, see a challenge or
  consume an existing confirmation. No permission decision is cached between
  calls; a permission revocation must block a later confirmation.
- Preserve `config_entry_id`, `loan_id`, `confirm`, `confirmation_id`, their
  schemas, `SupportsResponse.OPTIONAL`, ephemeral per-entry tokens, error/result
  behavior, trusted-system calls and per-entry session isolation.
- Admins/owners and ordinary Users succeed through their actual HA control
  policies. No custom per-account permission UI is added. HA's default Users
  group grants access to all entities; dashboard hiding does not restrict that.
  Account restrictions require HA permission policies that actually restrict
  those entities. This action does not grant or modify any permission.

## Verification and scope

Use TDD with real HA users, groups/PolicyPermissions, registry and service calls;
replace only upstream I/O where practical. Test ordinary non-admin success,
scoped access to one of two entries, read-only/no-control denial, wrong-platform
and missing-entity denial, unknown/inactive identity, renamed entities, admins,
trusted system calls, real server confirmation, denied token use and revocation.
Keep existing renewal/session/protocol suites green. Test actual Core/harness
2026.11.1 and minimum 2026.11.0, Ruff and official hassfest, then hosted CI.

Update current action descriptions and user docs, retaining historical released
notes and validation records. This request authorizes a PR, not another release
or a live renewal. The Solus client, coordinator and consent manager stay intact.

References consulted: [HA permissions](https://contributors.home-assistant.io/core/internals/permissions/)
and [action registration](https://contributors.home-assistant.io/core/integrations/actions/),
plus installed Core 2026.11.1 `helpers/service.py` and `auth/permissions`.
