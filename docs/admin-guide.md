# Administrator guide: SCIM provisioning and enforcement

This guide shows you how to turn on SCIM provisioning, connect your identity
provider (IdP), and write rules that remove access automatically. The SCIM
settings live in the Remediation page. Only system administrators can see
them.

## What SCIM provisioning does

Your IdP pushes user records to IAG over SCIM 2.0 (RFC 7644). IAG stores each
record as a provisioned identity keyed by the IdP's externalId. When a
provisioned user is disabled or deleted at the IdP, IAG reflects the change at
the next sync, so review data stays aligned with the directory.

The provisioning surface is off until you turn it on and generate a token.
Without a token the endpoints answer 503, and audits record nothing.

## Turn on SCIM provisioning

1. Sign in as a system administrator and open the Remediation page.
2. Find the SCIM provisioning card.
3. Tick Enabled.
4. Select Generate token.
5. Copy the token from the dialog and store it in your password manager.

The dialog shows the full token once. IAG stores only a hash of it. If you
lose the token, rotate it - the old one stops working the moment a new one is
issued.

To stop provisioning at any time, select Revoke. The endpoints answer 503
again. Your data stays.

## Connect your identity provider

Point your IdP's SCIM client at the base URL and give it the token.

Base URL: https://your-iag-host/api/scim/v2
Authorization header: Bearer your-token

Both Okta and Microsoft Entra ID work with these settings:

- authentication: bearer token
- unique identifier: externalId
- sync direction: push only (IAG does not pull)

### Choose the join key carefully

The externalId your IdP sends becomes the join key for the provisioned user.
Pick a stable identifier such as a UPN or an employee number. Do not use a
display name. If the join key changes, the user splits into two records and
their review history detaches.

### What the endpoints accept

IAG implements the SCIM 2.0 operations your IdP needs for user lifecycle:

- POST /Users - create a provisioned user
- GET /Users - list, with filters such as userName eq "jdoe@example.com"
- PATCH /Users/{id} - update attributes, including active true or false
- DELETE /Users/{id} - remove the provisioned user

Responses follow RFC 7644 error shapes. Bad credentials answer 401. A
disabled surface answers 503.

## Write enforcement rules

Enforcement rules revoke access at the directory when a reviewer revokes it in
a campaign. They give reviewer decisions teeth.

1. Open the Remediation page.
2. In New remediation rule, give the rule a name.
3. Set action to enforce.
4. Choose a target:
   - remove_entitlement removes the entitlement (directory group) named in the
     snapshot. The entitlement name must match the directory group name.
   - disable_account disables the user account. The connector matches the
     account attribute it is configured to match on.
5. Narrow the rule with filters if needed. Filters are ANDed. An empty filter
   matches everything.
6. Save the rule.

Enforcement actions require approval by default. An approver must release
each action before it runs. You can switch approval off per rule, but leave it
on until you trust the rule.

The action queue shows each enforcement action with its target. Approve,
cancel or retry from the queue. After an action completes, select Sync now to
pull the change back and close the drift window.

### What happens when a reviewer revokes access

1. The reviewer revokes access in a campaign.
2. Matching rules fire and create actions in the queue.
3. Actions that need approval wait for an approver.
4. Approved actions run against the directory through the source connector.
5. The sync at the next cycle (or Sync now) mirrors the change back into IAG.

Enforcement write-back runs through the source connector. Each adapter
writes in its own dialect: LDAP removes the user from the group or sets the
disable attribute; Entra ID removes the group membership or clears
accountEnabled; SQL runs the admin-supplied write statements. If the
directory already shows the clean state (the user was removed, the account
already disabled), the action completes as already clean without writing.
CSV and spreadsheet sources have no write-back; their actions fail with a
clear message and requeue for review rather than silently skipping.

### SQL sources

SQL connectors need the admin-supplied write statements in the connector
config. Put them where your DBA can review them. LDAP connectors perform the
standard directory operations.

## Troubleshooting

Your IdP reports a 503 from IAG
: The surface is off or the token is missing. Tick Enabled and generate a
  token.

Your IdP reports a 401
: The token is wrong or it was rotated. Rotate again and paste the new one
  into the IdP.

Provisioned users are duplicating
: The externalId your IdP sends changed. Check the IdP's identifier setting
  and re-map.

An enforcement action failed with "no enforcement write-back"
: The source is a CSV or spreadsheet source. These have no directory to
  write to. Point the rule at an LDAP, Entra ID or SQL source, or handle
  the revoke outside IAG.

An enforcement action completed but the directory did not change
: Check that the entitlement name matches the directory group name, and that
  the account attribute the connector matches on holds the value you expect.
  Then run Sync now.

## Where to read more

- RFC 7644 defines the SCIM 2.0 protocol
- The feature-6 specification covers the design decisions
  (SPECS/feature-6-scim-provisioning-enforcement.md)
