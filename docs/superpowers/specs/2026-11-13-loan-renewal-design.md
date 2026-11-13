# Explicit individual loan renewal

The owner's renewal request extends the original read-only v1 design with one
explicit action. Authentication, discovery, persistent entry DeviceIDs, loan
attributes, aggregate sensors and the read-only to-do entity stay as designed.
The APK establishes the protocol shape; no live renewal has been performed.

## Action and consent

Register `axiell_libraries.renew_loan` in integration `async_setup`, using the
current Home Assistant action APIs and `services.yaml`. Require a selected
`config_entry_id` and `loan_id`. Only administrators and trusted HA system
contexts may invoke this account-level write. Do not install automatic renewals
or bulk actions. Use `SupportsResponse.OPTIONAL`: response callers receive a
small result; ordinary action callers receive informative translated exceptions
when consent or intervention is needed.

Resolve a loaded Axiell entry server-side, then refresh authoritative loans and
find that loan in that account. Reject absent, nonrenewable or missing-source
loans. Neither the caller nor another entry supplies Source or account UserID.
Use the same account UserID as existing LoansGet. Shared bibliographic record
IDs never identify the loan to renew.

A known positive renewal cost requires local explicit consent before writing.
Display the amount without inventing a currency. This is not a new cost-check
API. A server challenge also requires explicit consent, even after local cost
consent. Display bounded, plain-text, secret-redacted `statusmessage` and issue a
random, short-lived `confirmation_id`. The user must submit a second action
with that ID and `confirm: true`. Both fields are required together. Raw server
acknowledgement codes are never accepted from callers.

Pending confirmations live only in the entry's memory: expire after 600 seconds
using monotonic time, one pending token per loan, at most 32 per entry. Consume a
valid token under the operation lock before any await; never restore it after
a failed attempt. Bind it to the loan, source and original circulation fields
(loanID, itemID, recordID, Source, dueObject, canRenew, RenewalCount,
RenewalsRemaining, renewalCost, OverdueSpecified and Overdue). Metadata enrichment
does not invalidate consent. Changed circulation state requires a fresh action
and new consent. Reload/unload clears pending consent. Cross-account tokens and
replays cannot write.

Preserve exact server challenge status strings internally. Append a code only
after the user explicitly confirms its message. Join codes with semicolons;
initial PromptAcknowledged is empty. Reject unsafe codes (controls, semicolons,
surrounding whitespace, more than 128 characters), repeated codes and chains
longer than five acknowledgements. Never invent a server code for local cost
consent. Unknown/malformed responses cannot grant consent.

## Transport and failures

Use the existing active HTTPS server, wrapper, cookies and catalogue headers for
`Cat.asmx/LoanRenew`. Request is exactly LoanID, UserID, Source and
PromptAcknowledged. Use existing SessionID, AuthToken and persistent DeviceID;
no login or device registration solely to renew. The success-only decoder for
existing reads/authentication must remain strict; only renewal decodes explicit
error and confirmation statuses.

Success refreshes loans and publishes coordinator data immediately. A provider
`error` stops and surfaces its sanitized message. Unknown outcomes (timeout,
transport failure, HTTP error, malformed response or session rejection after
dispatch) trigger a read reconciliation, never an automatic repeat of LoanRenew.
Read recovery may use the existing one-time reauthentication with the stored
DeviceID. A later explicit attempt must complete a fresh preflight first.
Observed loan changes cannot prove which write succeeded.

Preserve the distinction between a successful write with failed HA refresh and
an uncertain write. Response callers receive `status: renewed` and
`refreshed: false` for the former. Ordinary callers receive an explicit partial
success error telling them not to repeat renewal solely to refresh HA. Pending
consent returns `status: confirmation_required`, message, confirmation_id and
expires_in. Rejections and uncertain outcomes use HA exceptions, not error codes
disguised as successful responses.

Provider messages are a privacy boundary: remove HTML/control content, redact
known card/PIN/authentication/session/device/cookie values and encoded forms,
and bound output to 512 characters. Snapshot secrets before transport can clear
them, include response cookies, and never log raw messages, response bodies or
codes. Known-secret redaction cannot guarantee removal of arbitrary personal
text returned by a provider; document this limit. Exceptions crossing the
coordinator logging boundary contain only static messages.

## Lifecycle and architecture

Keep `ConfigEntry[AxiellCoordinator]`. Add a focused `renewal.py` for per-entry
consent/workflow state, and `services.py` for the HA action adapter. A single
per-coordinator operation lock serializes polling, login recovery and renewal
transactions. Refactor the existing refresh body into a private unlocked helper;
publish a postwrite refresh directly, never await public coordinator refresh
while holding its lock. Explicitly initiate reauth when a direct publication
fails authentication; `async_set_update_error` alone does not do that.

Cancellation must not leave a detached HTTP write racing another operation.
Retain and drain any shielded transaction. Unload marks the entry closing,
rejects queued/new actions and drains active operations before session detach.
Normal read/write HTTP timeouts stay bounded. No new device, entity per loan,
queue, persistence layer or third-party dependency is needed.

## Verification and delivery

Use Superpowers subagent implementation, TDD and independent task reviews.
All tests are offline and synthetic. Verify exact envelopes and routing,
challenge chains, fee consent, account/loan isolation, stale/replayed tokens,
expired sessions, lost replies, cancellation/unload and read-only entities.
Run the full suite on actual Home Assistant 2026.11.1 and minimum 2026.11.0,
Ruff and official hassfest, then hosted CI. Prepare version 0.4.0 and release
notes using the existing validated semantic-release workflow. Do not publish a
release or invoke a live renewal. Create a PR, report executed evidence and
state that provider challenge semantics and end-to-end renewal remain unverified.

Official action documentation consulted:
https://contributors.home-assistant.io/core/integrations/actions/
