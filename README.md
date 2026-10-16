# Melusense Benchmark

Private, agent-visible starting point for independent Kolibri, Mistral and Qwen
implementations of an offline email pipeline. This is an intentionally incomplete
challenge, not the reference implementation and not an accuracy result.

Start with [MANIFEST.md](MANIFEST.md), [AGENTS.md](AGENTS.md), [TASKS.md](TASKS.md)
and the [API contract](docs/contract.md). The coordinator freezes the reviewed
initial commit as `benchmark/base-v1`; every trial must record its exact SHA.

```bash
python3 -B tools/verify_scaffold.py
python3 -B -m unittest discover -s tests -p 'test_scaffold.py'
python3 -B -m unittest discover -s tests -p 'test_acceptance.py'
```

The first two commands validate the starter. The final command intentionally
fails on the unimplemented parser: these are visible candidate acceptance tests.
Never count scaffold checks as parser success. Python >=3.12 is the trial target;
all initial source uses the standard library.

No reference source, real mail, private corpus, Gold, hidden tests, credentials,
agent history or prior model output belongs in this repository. The three public
fixtures are fabricated and use reserved example.invalid addresses.
