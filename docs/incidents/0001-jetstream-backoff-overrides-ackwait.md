# 0001: JetStream redelivered messages mid-LLM-call

**Symptom.** A real job failed with "API key no longer available; please
resubmit" — yet the PDF rendered fine and landed in S3. The job row said
`failed`, the artifact said `succeeded`.

**Investigation.** Traced the job's events on its `cv.{job_id}.*`
subjects; ai-processor logs showed the `requested` message delivered
**twice**. The second delivery hit the `GETDEL` path after the key was
already consumed → `API_KEY_MISSING_ERROR`. But why redeliver at all?
`AckWait` was set to 5 minutes. Asked the server directly
(`nats consumer info`): effective `ack_wait: 10s`.

**Root cause.** The consumer had a `BackOff` list. JetStream semantics:
**a `BackOff` list *replaces* `AckWait` as the redelivery timer** —
`backoff[0]` (10s) became the effective ack wait, so any LLM call longer
than 10s got redelivered while still in flight.

**Fix.** Removed `BackOff` entirely (in-process retries already cover
transients). Added stage-aware failure marking: `MarkFailedProcessing`
only transitions from `pending`, so a late failure event can't clobber a
job that already progressed. Recovered the two mislabeled rows with a
one-off SQL UPDATE.

**Lesson.** Verify effective server-side config, not what you passed to
the client. `nats consumer info` > assumptions.
