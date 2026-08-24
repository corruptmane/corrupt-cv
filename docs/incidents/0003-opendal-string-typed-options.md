# 0003: OpenDAL panicked on boolean options

**Symptom.** Python services panicked configuring the S3 operator.

**Root cause.** OpenDAL operator options are **string-typed**; passing
Python `False` instead of `"false"` (e.g. `enable_virtual_host_style`)
blows up in the Rust core.

**Fix.** All options passed as strings; later promoted to a proper
`s3_use_path_style` setting so compose (Swift, path-style) and prod
(AWS, virtual-host) diverge by config, not code.
