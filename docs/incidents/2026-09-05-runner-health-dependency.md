# Host Core runner dependency and SES reconciliation — 2026-09-05

Production ship `33964942587` on `c7f73b4013fe50f27e11c2838fdb5cc71f1a1d8d`
confirmed that the durable schema ledger and migration checkpoint repair work.
At 12:08:00 UTC the checkpoint reported migrationComplete=true, and no D1
re-import or secret transfer ran. At 12:08:28 UTC Host Core became the delivery
owner and both new workers started without a DDL deadlock.

Immediately afterward, the runner-side public health CLI failed importing
`yaml`: Production Host Core set up a fresh Python interpreter without the
PyYAML dependency already installed by the other production workflows. The
failure handler paused both workers at 12:08:50 UTC. Subsequent Airflow/Sender
deployments and final acceptance did not run; no 0.7.0 tag was published.

The workflow now explicitly installs pinned PyYAML and invokes the health
CLI's credential-free `--help` path before SSH identity setup or any production
mutation. Regression tests preserve this ordering and execute the CLI import.
All existing exact-SHA, Environment, migration and delivery gates remain.

The same investigation found that the Python Tencent SES normalizer omitted
the provider's documented processing failure codes (for example 1006 frequency
control and 1010 daily quota), leaving such sends pending. Explicit failures
now become failed; record-not-found 2001 stays unconfirmed. Queued/delayed
receipts never become delivered merely because a timestamp exists. Fifty-six
offline cases cover numeric/string failure codes, delivery, rejection, absence
and timestamp overflow. This does not replay or send any messages.

Primary provider contract: https://cloud.tencent.com/document/api/1288/51053#SendEmailStatus

Production completion must still be recorded from a subsequent successful full
ship and actual natural delivery acceptance, not inferred from these changes.
