# 0012: S3 existence obfuscation vs the deep readiness probe

**Symptom.** Every gateway canary retry failed identically:
"canary deployment gateway.cvgen not ready". The canary pod booted fine
(jetstream provisioned, servers listening) but its readiness probe
returned `503` with body `object storage unreachable`, forever. The old
primary — running the pre-probe image — served traffic unaffected,
which is why the site stayed up while promotion was impossible.

**Investigation.**
1. Port-forwarding into the unready pod named the failing dependency:
   object storage. The probe called `HeadBucket`.
2. `infra/opentofu/iam.tf` says it out loud: the app user is granted
   exactly `s3:GetObject` + `s3:PutObject` on `cvs/*` — "**No
   ListBucket**: the gateway maps NoSuchKey to a 404 on its own."
   `HeadBucket` requires bucket-level permission → 403, forever.
3. Switching the probe to a GET of a nonexistent key should have been
   the fix. Verified live with the production credentials:

   ```
   aws s3api get-object --key cvs/.readyz-probe ...
   An error occurred (AccessDenied) ... not authorized to perform:
   s3:ListBucket on resource "arn:aws:s3::<bucket>"
   ```

   Not 404 — **AccessDenied naming `s3:ListBucket`**. HEAD behaves the
   same.

**Root cause.** S3 *existence obfuscation*: when the principal lacks
`s3:ListBucket`, S3 refuses to reveal whether a missing key exists, and
answers reads of it with `AccessDenied` instead of `NoSuchKey`. Under
this deliberately least-privilege policy, **no read-probe of a
nonexistent key can ever succeed** — GET or HEAD. The W5 probe design
("head-bucket") was written without checking the IAM grant surface it
depends on.

**Fix.** Probe with actions the policy actually grants: a write +
read-back round-trip on a fixed marker key
(`PutObject` → `GetObject` → close). This proves reachability,
authentication and authorization end-to-end using only granted
actions, at the cost of leaving one ~2-byte marker object
(`cvs/.readyz-probe`) permanently in the bucket. Also required adding
`Client.Put` to the gateway's storage client, which had been
download-only since v1.

**Related non-bug:** the AWS SDK Go v2 does not type HeadObject 404s as
`types.NotFound` (empty error body, generic wrapper) — but after root
cause #3 this stopped mattering; keep it in mind for any future
HEAD-based checks.

**Lesson.**
1. Design readiness probes against the *exact* IAM grant surface: read
   the policy document as part of the probe spec. Least-privilege
   policies and convenient "does it work?" probes are natural enemies.
2. On S3, absence-of-ListBucket turns every missing-key read into
   `AccessDenied`. If you need an authorized-404 signal, grant
   `s3:ListBucket` — or probe with mutations you do have.
3. Process note: this failure hid underneath incident
   [0011](0011-netpol-default-deny-behind-cilium-gateway.md) — two
   independent readiness killers were live at once, and fixing only the
   loud one changed nothing visible. When layered failures present as
   one symptom, isolate each layer before believing any fix.
