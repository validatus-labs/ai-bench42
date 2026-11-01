# With and without cache calibration

The comparison checked all 128 model-facing inputs and retained identical
questions, output budgets, checkpoint, packages and task scorers. Each cohort
repeated the same 32 examples per task three times.

| Task | Before | After | Difference, percentage points |
| --- | ---: | ---: | ---: |
| IFEval strict / loose | 91.67% | 88.54% | −3.125 |
| MMLU-Pro | 45.83% | 50.00% | +4.167 |
| BBH date | 84.38% | 84.38% | 0 |
| BBH three-object logic | 100.00% | 100.00% | 0 |

Output caps fell from 53 to 51 of 384 responses. Generated tokens, including
reasoning, rose from 491,665 to 504,338: 12,673 more, about 2.58%. General-run
elapsed time was approximately 249 minutes in both cohorts; calibration,
deployment and rejected-attempt costs are additional and excluded from that timing.
Both basic tool cohorts passed nine calls on three distinct cases.

The historical baseline was warm/shared. Cache history, time, thermal conditions
and system-library effects were not fully controlled. Short serving observations
therefore cannot isolate a calibration-only speed effect. Hardware details and
portable throughput claims are withheld.

## Short serving observations

Nine runs per cohort used 54 requests with short synthetic prompts, 64 requested
output tokens and an already warm serving workload. The table shows means of
three run means per client count, not pooled tail percentiles. Output throughput
uses actual server-generated-token deltas divided by measured run duration.

| Clients | TTFT before / after, ms | ITL before / after, ms | Output tokens/s before / after |
| --- | ---: | ---: | ---: |
| 1 | 221.7 / 231.4 | 27.54 / 27.12 | 33.15 / 33.40 |
| 2 | 1780.5 / 1574.3 | 31.11 / 27.13 | 31.60 / 36.01 |
| 4 | 4400.7 / 3895.7 | 32.80 / 29.16 | 29.87 / 33.60 |

Token-count definitions can differ between server usage and client retokenization;
these figures use server usage. Prefix-cache hit-token ratios were 9.88% at one
client and 99.35% at two/four in both cohorts. More clients queued against one
serving sequence: this is not parallel decoding or full-context performance.
Hardware identity and allocation data are withheld, so this table is a historical
within-project observation, insufficient for an external hardware comparison.

The result is mixed, not a universal gain. The rejected export remains a separate
failure, not a valid final cohort. There is no controlled coding result showing
calibration caused or cured the later parser failures.

[Report index](README.md) · [Methods and publication scope](METHODS.md)
