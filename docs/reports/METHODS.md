# How to read and share these reports

These are edited editions of 32 retained project result reports. They cover
preparation, serving, general evaluation, calibration, tool use and coding trials.
They are a historical result collection, not a new benchmark run, release gate
or claim that the full engineering challenge passed.

## What we keep

Keep the question, method, sample size, denominator, output limits, observed
result and unresolved issues together. Separate model behavior from controller
failures, completed experiments from preparation, and independent coding from
assisted development. Repetitions on the same questions are not new independent
samples. Supplemental contract probes are not a percentage of product completion.
NOT_EVALUATED is not zero accuracy; a preserved failed run does not become PASS
when a future controller fix is written.

The reporting approach follows the emphasis on evaluation context and limitations
in [Hugging Face model-card guidance](https://huggingface.co/docs/hub/model-cards)
and the separation of scenarios and multiple metrics in
[HELM](https://arxiv.org/abs/2211.09110). We apply these principles to project
reports; this collection is neither a HELM evaluation nor an official model card.

## What is withheld

Hostnames, accounts, machine inventories, hardware identifiers, IP addresses,
ports, filesystem locations, process/session identities, private source hashes,
authentication material and internal evidence links are omitted. The overview
uses fictional Alice and Bob. No raw correspondence, annotation payloads,
reference implementation, candidate source, hidden tests, screenshots or raw
agent reasoning is exported.

Software/model names, relevant serving settings, counts and experimental
limitations remain. Editorial summaries condense the technical records; they
are not verbatim replacements or independently re-executed audits. Inventory
reports deliberately retain only method and scope because their measurements
would disclose the excluded machine details. No substitute measurements are
invented.

Private evidence retains source bindings and the original independent reviews.
Publication review checks these editions against those records, but it is not
a new independent scientific replication. Published-file SHA-256 values identify
only this edited collection; they do not expose private runtime or source pins.

## Reproducibility limits

The general comparison uses the same fixed 128 unique English examples, repeated
three times per cohort, with a 4,096-token output cap including reasoning. Exact
row manifests and private runtime bindings are not in this collection, so these
editions alone are insufficient to reproduce the selection bit for bit.
The reports describe methods and observed outcomes while protecting internal
records. No full-suite score, controlled cross-model ranking or held-out email
precision, recall or F1 is claimed.

Hardware and some runtime metadata are withheld, so serving observations cannot
be used as a portable performance comparison. Time, cache history and other
uncontrolled differences limit calibration causality. Guided and independent
coding used different conditions and must not be pooled as equal repetitions.

## Keep reports outside the coding worker

This collection is for readers and coordinators. It contains lessons from prior
trials and must not be mounted into a fresh independent candidate workspace or
silently added to its offline assignment. Use the separately approved, pinned
assignment package; do not treat the commit adding these reports as a new trial
freeze. Source, API, tests and budgets and old freeze references are unchanged by this
documentation publication. A future package builder must explicitly exclude
evaluation reports and requalify its contents before use.

## Publication boundary

The owner authorized pushing the edited collection to the existing repository.
Its visibility remains private. The sanitization scope is this report collection,
not every existing repository file, Git metadata, earlier commit or linked page.
Existing documentation may still contain operational details. This publication
does not certify the whole repository for public release.

Deleting identifiers from a new edition does not remove them from old history;
[GitHub documents the separate consequences of history rewriting](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).
No history rewrite, force push or visibility change is part of this work.

[Report index](README.md) · [Reader overview](kolibri-overview.md)
