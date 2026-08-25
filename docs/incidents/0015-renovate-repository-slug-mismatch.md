# 0015: Renovate configured against the wrong repository slug

**Symptom.** Found during owner review of the Renovate bootstrap, before
any run mattered: `RENOVATE_REPOSITORIES` pointed at
`corruptmane/cv`, while the repository is `corruptmane/corrupt-cv`
(the working directory is locally named `cv`). Left unnoticed, every
self-hosted run would have failed against a nonexistent repo — or worse,
been misconfigured silently once a same-named repo appeared.

The sweep also surfaced that the entire Go module identity
(`github.com/corruptmane/cv/services/gateway`), all import paths, the
buf managed `go_package` prefix, the serialized paths inside generated
protobuf code in both Go and Python, and a test fixture URL carried the
short name.

**Root cause.** References were written from memory of the local
directory name instead of verified against the remote. Nothing validates
that config-as-code identifiers match live repository metadata.

**Fix.** Repo-wide word-boundary rename to `corruptmane/corrupt-cv`
(workflow env, module, imports, buf prefix), canonical regeneration of
all protobuf codegen, drift-guard re-check, and full floors plus
golangci-lint before landing — the renamed module rode its own successful
CI and image build.

**Lesson.** Config-as-code inherits the same discipline as code: any
identifier naming an external system gets verified against that system
at write time (`git remote -v`, an API call), never recalled from the
local environment's naming.
