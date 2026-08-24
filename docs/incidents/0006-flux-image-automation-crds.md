# 0006: Flux image automation — CRDs missing

**Symptom.** `cvgen-image-automation` Kustomization: `no matches for kind
"ImagePolicy"`.

**Root cause.** The cluster's Flux bootstrap didn't include the
image-automation controllers — they're `--components-extra`, not default.

**Fix.** Re-bootstrap:
`flux bootstrap ... --components-extra=image-reflector-controller,image-automation-controller`.
