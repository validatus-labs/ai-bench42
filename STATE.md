# AI-Bench42 — Research preview

The current source integrates the verified Kolibri-only coordinator, native Kilo
worker transport, deployment/adoption, monitoring, scored adapters and resumable
execution. [Results](docs/reports/README.md), [assessment](docs/reports/kolibri.md)
and [methodology](docs/reports/methodology.md) summarize the latest reviewed cohort.

On 6 November 2026 three independent Kolibri trials completed. None met the full
parser contract; two passed all 21 supplied tests, with 4/11 and 7/11 additional
probes. The third left the starter unchanged. The selected measurement workflow
finished and reused its results without new model requests. Held-out accuracy is
NOT_EVALUATED. These are distinct outcomes, not a full benchmark PASS.

The complete source package has an offline verification command:

```bash
python3 -B scripts/verify-package.py --output build/package-acceptance
python3 -B scripts/verify-publication.py --check
```

Live coding requires qualified host/tool/data profiles and approved private TRAIN
inputs. The provided profiles are not proof those assets exist on a new machine.
SWE-bench, matched other-model comparison and fresh-machine installation remain
outside the verified result. The parser in this repository is the empty task
starter, not a distributed finished reference or successful Kolibri candidate.

Original numerical budgets, API, task requirements and provided tests are retained.
The source includes reader reports and evaluator tools: use the reviewed
[assignment exporter](tools/assignment.py) for fresh blind workers. Protect
private data and live services; apply the [runbook](docs/RUNBOOK.md).
