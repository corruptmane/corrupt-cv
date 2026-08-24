# Runbook — cvgen-db Postgres backup & restore (PITR)

CloudNativePG 1.28.x, single-instance cluster `cvgen-db` in namespace `cvgen`,
base backups + WAL archive to S3 via native `barmanObjectStore` (deprecated
upstream, accepted — see `deploy/k8s/db/cluster.yaml`). Secrets flow
tofu → SSM → ESO → Secret (ADR 0013); Postgres choice is ADR 0008.
**No real bucket name appears anywhere in this repo or runbook — always
`<bucket>` or `$CVGEN_BACKUP_DESTINATION`.**

---

## 1. Preconditions

1. **Owner manual step (tofu side):** `homelab-private` creates SSM
   SecureString `/homelab/cnpg-backup-bucket-name` (plus the two key params).
   The bucket name lives only in tofu state and SSM — never here. The bucket
   itself pre-exists (fleet-created); this repo does not create it.
2. **Fleet-side registration BEFORE merge takes effect:** a Flux Kustomization
   for `deploy/k8s/secrets` exists, and the `cvgen-db` Kustomization carries
   `postBuild.substituteFrom: [{kind: Secret, name: cvgen-db-backup}]`
   (`optional` NOT set = fail-loud if the Secret is absent). Order matters:
   the Secret must exist before the db Kustomization can substitute.
3. Confirm ESO `ClusterSecretStore` `aws-ssm` is healthy:

   ```sh
   kubectl get clustersecretstore aws-ssm -o jsonpath='{.status.conditions[*].type}'
   # expect: ... Ready
   ```

## 2. First apply — what to expect

Apply order: secrets dir first, then db dir (fleet reconciles both; verify in
this order manually).

```sh
kubectl get externalsecret cvgen-db-backup -n cvgen
kubectl get es cvgen-db-backup -n cvgen -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'
# expect: True
```

```sh
kubectl describe secret cvgen-db-backup -n cvgen
# expect exactly 3 keys: ACCESS_KEY_ID, SECRET_ACCESS_KEY,
# CVGEN_BACKUP_DESTINATION (= s3://<bucket>/cvgen), plus label cnpg.io/reload=""
```

Then, after the db Kustomization reconciles:

- **CNPG webhook emits a deprecation warning event** for native
  `barmanObjectStore`. Expected; do not page anyone.
- **NO pod restart, NO PVC rebuild** — adding `.spec.backup` to a running
  cluster is dynamic (`archive_mode` already on, `archive_command` fixed at
  `/controller/manager wal-archive`). Verify pods did not roll:

  ```sh
  kubectl get pods -n cvgen -l cnpg.io/cluster=cvgen-db -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.startTime}{"\n"}{end}'
  # startTimes unchanged vs. before apply
  ```

- WAL archiving begins dynamically. Verify:

  ```sh
  kubectl cnpg status cvgen-db -n cvgen
  # "Continuous Backup" section: point of recoverability advancing,
  # WAL archiving working (no "not available"/error lines)
  kubectl get backup -l cnpg.io/cluster=cvgen-db -n cvgen
  ```

  NOTE: the `kubectl-cnpg` plugin has **no `backup list` subcommand** —
  listing backups is plain `kubectl get backup`.

## 3. Backup inventory

```sh
kubectl get scheduledbackup -n cvgen                 # cvgen-db-scheduled, last check time
kubectl describe backup <name> -n cvgen              # phase=completed, size, WAL range
kubectl cnpg status cvgen-db -n cvgen --verbose      # full backup/WAL detail
```

First backup fires immediately (`immediate: true`) at reconcile; afterwards
daily 03:30 UTC.

## 4. Restore drill (PITR)

Scale down consumers (gateway Deployment) or accept a downtime window —
during the drill writes to the old cluster are lost after cutover.

Recovery Cluster manifest template (new cluster, new name). CRITICAL nuance:
objects live under `s3://<bucket>/cvgen/<serverName>/...` where `serverName`
defaults to the ORIGINAL cluster name `cvgen-db`. The
`externalClusters[].barmanObjectStore` MUST set `serverName: cvgen-db`, or
barman looks under `s3://<bucket>/cvgen/cvgen-db-recovery/` and finds nothing.

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: cvgen-db-recovery
  namespace: cvgen
spec:
  instances: 1
  storage:
    size: 5Gi
    storageClass: longhorn
  bootstrap:
    recovery:
      database: cvgen
      owner: cvgen
      source: cvgen-db-recovery          # name of the externalClusters entry below
      recoveryTarget:
        targetTime: "2026-08-20 14:30:00+00"   # RFC3339-ish UTC; operator picks
                                               # closest base backup BEFORE target,
                                               # then replays WAL up to it
  externalClusters:
    - name: cvgen-db-recovery
      barmanObjectStore:
        serverName: cvgen-db             # <-- folder of the ORIGINAL cluster in S3
        destinationPath: s3://<bucket>/cvgen   # same value as $CVGEN_BACKUP_DESTINATION
        s3Credentials:
          accessKeyId:
            name: cvgen-db-backup
            key: ACCESS_KEY_ID
          secretAccessKey:
            name: cvgen-db-backup
            key: SECRET_ACCESS_KEY
        wal:
          compression: gzip
        data:
          compression: gzip
```

Steps:

1. Render the template with a real `targetTime` (UTC, just past the incident)
   and apply it. The bootstrapped recovery cluster is a NEW Cluster named
   `cvgen-db-recovery` — the original stays untouched.
2. Watch it restore base backup then replay WAL:

   ```sh
   kubectl get cluster cvgen-db-recovery -n cvgen -w
   # phase: recovery scan -> wal restore -> ... -> cluster in healthy state
   ```

3. Validate data (section 5), then promote/repoint apps by updating the
   `DATABASE_URL` secret (CNPG-generated secret `cvgen-db-recovery-app`,
   key `uri`) — or rename the recovered cluster to `cvgen-db` after
   validation if you want the original identity back.

## 5. Post-restore sanity

```sh
kubectl exec -it cvgen-db-recovery-1 -n cvgen -- psql -U postgres -c '\l'
# expect: cvgen database present, owner cvgen

kubectl exec -it cvgen-db-recovery-1 -n cvgen -- psql -U cvgen -d cvgen -c \
  'SELECT count(*) FROM jobs;'
# expect: plausible row count for targetTime (compare against incident report)

kubectl exec -it cvgen-db-recovery-1 -n cvgen -- psql -U cvgen -d cvgen -c '\dt'
# expect: migrations table present (goose)

kubectl exec -it cvgen-db-recovery-1 -n cvgen -- psql -U cvgen -d cvgen -c \
  'SELECT version_id, is_applied, tstamp FROM goose_db_version ORDER BY id DESC LIMIT 5;'
# expect: highest applied version_id matches pre-incident state
# (do NOT exec into the cvgen-migrate Job pod — it exits Completed, and
# exec needs a running container; query goose_db_version directly instead)
```

## 6. RTO/RPO measurement

Fill in after the first real drill. RPO ≈ (targetTime − last archived WAL);
RTO ≈ wall clock from declaring disaster to app serving reads/writes.

| Drill date | Incident sim | targetTime | Last WAL archived | RPO | RTO | Notes |
|---|---|---|---|---|---|---|
|           |              |            |                   |     |     |       |
|           |              |            |                   |     |     |       |

## 7. Credential rotation

ESO re-reads SSM hourly (`refreshInterval: 1h`) and rewrites Secret
`cvgen-db-backup`. The `cnpg.io/reload: ""` label — set inside the ESO
`target.template`, because defining a template suppresses ExternalSecret
label copying — asks CNPG instances to hot-reload the credentials without a
restart.

Known caveat: CNPG cache bugs (#4914, #3287) mean rotated keys are sometimes
NOT picked up despite the label. Symptom of missed pickup: WAL archiving
auth failures in instance logs (`kubectl logs cvgen-db-1 -n cvgen | grep
wal-archive`). Remedy:

```sh
kubectl cnpg reload cvgen-db -n cvgen
```

After rotating keys in SSM, watch one refresh cycle; if archiving errors
appear, run the reload above and confirm the Continuous Backup section goes
green again.
