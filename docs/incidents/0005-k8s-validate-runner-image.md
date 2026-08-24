# 0005: CI k8s-validate job fought the runner image

**Symptom.** `"/usr/local/bin/kustomize exists"` — the install step
failed because GitHub's runner already ships kustomize.

**Fix.** Use the preinstalled kustomize; install only kubeconform.
Validate rendered manifests with `-strict` + the datree CRDs catalog for
schema coverage of Flux/Flagger/VM CRDs.
