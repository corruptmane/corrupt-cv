# Fleet contract

`deploy/k8s/` and the homelab fleet repo (`corruptmane/homelab`) are two
public repos that share identifiers: SSM parameter names, in-cluster
service FQDNs, the DNS host, the cert issuer, the storage class. When one
side renames its half, the other breaks at reconcile time — possibly days
later, during an unrelated deploy. This contract makes the shared surface
explicit: every cross-repo identifier is declared once in
`deploy/k8s/infra/fleet-inputs.yaml` (a plain ConfigMap,
`cvgen-fleet-inputs`) and explained here.

The ConfigMap is **documentation-as-data**: no controller reads it, no
template expands it. Its job is blast-radius greppability — before merging
a rename, `grep -rn <value> deploy/ infra/ docs/` tells you exactly what
else has to move, and during an incident it tells you which cluster-side
object a cryptic FQDN belongs to.

## The inventory

Mirrors the `data:` keys of `cvgen-fleet-inputs`. Line numbers refer to
this repo at the time of writing; re-verify with grep after any edit.

| ConfigMap key | Consumed at | Notes |
|---|---|---|
| `cluster_secret_store` | `deploy/k8s/apps/externalsecret.yaml:12-14`; `deploy/k8s/secrets/backup-external-secret.yaml:28-30` | ClusterSecretStore `aws-ssm`, region eu-central-1; the store object itself is fleet-owned (ADR 0013) |
| `ssm_prefix_fleet_owned` | convention, no single consumer | `/homelab/**` is reserved by the fleet's tofu; everything cvgen writes lives under it |
| `ssm_params_cvgen_owned` | written by `infra/opentofu/ssm.tf:7,13,19,25,31,44`; read by `deploy/k8s/apps/externalsecret.yaml:21-36` | six parameters (`cvgen-s3-endpoint`, `-region`, `-bucket`, `-access-key-id`, `-secret-access-key`, `cvgen-session-secret`); prefix default `/homelab` in `infra/opentofu/variables.tf:16` |
| `ssm_params_backup` | `deploy/k8s/secrets/backup-external-secret.yaml:45-51` | synced into Secret `cvgen-db-backup` for CNPG barmanObjectStore; access-key-id and secret-access-key are written by homelab-private tofu, but the `bucket-name` parameter is created MANUALLY there — an owner step, not repo automation |
| `alertmanager_url` | none in this repo's manifests | fleet-side Alertmanager → Telegram pipe (ADR 0015); appears in this repo only in docs (`docs/k8s/alerting.md` §Routing) |
| `otel_collector_endpoint` | `deploy/k8s/apps/gateway.yaml:51-52`; `deploy/k8s/apps/ai-processor.yaml:32-33`; `deploy/k8s/apps/cv-generator.yaml:37-38` | OTLP/HTTP :4318 as `OTEL_EXPORTER_OTLP_ENDPOINT`; collector runs fleet-side in namespace `monitoring` |
| `vmsingle_url` | `deploy/k8s/canary/metric-templates.yaml:16,30`; `deploy/k8s/infra/flagger.yaml:28` | Prometheus-compatible query API :8428 for canary gates and Flagger's metricsServer; manual queries per `docs/k8s/alerting.md:13` |
| `victoria_logs_url` | none in this repo's manifests | log-query surface for first response; docs only (`docs/k8s/alerting.md:50`, `docs/k8s/homelab-integration.md:40`) |
| `dns_host` | `deploy/k8s/apps/gateway-api.yaml:22,26`; `deploy/k8s/apps/certificate.yaml:10`; `deploy/k8s/canary/canary.yaml:18,50` | Gateway listener hostnames, Certificate dnsNames, Flagger `service.hosts` + loadtester `-host`; the Cloudflare record itself is managed fleet-side via external-dns off Flagger's HTTPRoute |
| `cert_cluster_issuer` | `deploy/k8s/apps/certificate.yaml:11-13` | ClusterIssuer `letsencrypt-production`, Cloudflare DNS01; fleet-owned |
| `storage_class` | `deploy/k8s/db/cluster.yaml:14`; `deploy/k8s/infra/nats.yaml:33` | Longhorn for the CNPG data PVC and the NATS JetStream fileStore PVC; fleet-installed |
| `cnpg_image_pin` | deliberately absent | PG17 is pinned fleet-side by cluster convention; `db/cluster.yaml` has no `imageName`, so the operator takes the cluster-default major |
| `flux_kustomization_chain` | fleet repo, `apps/cvgen/` Kustomizations | dependsOn order `infra -> secrets -> db -> migrations -> apps -> canary -> image-automation -> alerting`; `secrets` and `alerting` entries are new and pending fleet registration |

## What lives WHERE

This repo owns manifests: everything under `deploy/k8s/` plus the one
piece of external infrastructure, `infra/opentofu/` (S3 bucket, IAM user,
the six cvgen-owned SSM parameters). The fleet repo owns the Flux
plumbing: the `GitRepository` pointing at this repo and the
`Kustomization` pointers under `apps/cvgen/`, wired in the dependsOn chain
above. Two of those entries do not exist yet — `deploy/k8s/secrets/` (the
backup ExternalSecret) and `deploy/k8s/alerting/` (the golden-signals
VMRule) ship in this repo but await their fleet-side Kustomization.

Fleet-side wiring this repo deliberately does not contain:

- the `postBuild.substituteFrom` (Secret `cvgen-db-backup`) on the db
  entry, which substitutes `${CVGEN_BACKUP_DESTINATION}` into
  `db/cluster.yaml:41` before apply — the placeholder never reaches the
  API server unexpanded;
- the future `secrets` and `alerting` Kustomization entries;
- the ClusterSecretStore, ClusterIssuer, monitoring stack, Longhorn and
  external-dns — cluster-shared objects consumed by, not defined in,
  this repo.

## Change protocol

Renaming or moving anything in the inventory means ONE PR touching three
places together:

1. the value(s) at their point(s) of use;
2. `deploy/k8s/infra/fleet-inputs.yaml` (and the consumer pointers in its
   leading comment);
3. this document's inventory table;

plus the counterpart change merged in `corruptmane/homelab` (fleet-side
SSM names, Alertmanager routes, external-dns expectations). If a rename
cannot update both repos atomically, stage it: add the new identifier to
both sides first, migrate consumers, then remove the old one in a follow-up.
Before merging, prove the blast radius:

```sh
grep -rn "letsencrypt-production\|longhorn\|cv.corruptmane.xyz" deploy/
grep -rn "/homelab/" deploy/ infra/opentofu/
kubectl kustomize deploy/k8s/infra | grep -A20 cvgen-fleet-inputs
```

## Why declared-not-templated

The obvious alternative — one values file expanded into every manifest via
kustomize `replacements` or Helm — would make this repo DRYer and the
audit worse. Templating hides values behind indirection: `grep` for
`vmsingle` would return a variable name, not the FQDN, and "what breaks if
this changes" becomes a question about generator semantics instead of a
flat search. Ops artifacts are read far more often than they are written;
duplication is the cheaper failure mode, and drift between the hardcoded
value and the declaration is caught by the change protocol above, not by
trusting a renderer. The single sanctioned substitution is the backup
destination path — because its input is a secret value (the bucket name)
that must never appear in either git repo (ADR 0013).
