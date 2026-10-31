# Browser qualification: observed boundary gaps

The installed Brave, Node and Playwright MCP module seal matched the existing runtime,
and a prior Kolibri session had proved real tool use. The important gaps concerned
scope, not the mere existence of a browser.

The inspected MCP configuration defaulted to allowing origins and did not enable
service-worker blocking. The backend shared the coordinator's filesystem and
network namespaces. Metadata checks showed other private working areas visible
to the same user; protected contents were not read. One attempted outside-file
API check failed inconclusively and was not counted as proven denial.

Missing restrictions, observed shared visibility and untested exposure were
reported separately. These findings did not demonstrate that a malicious page
had run or data had leaked. A proposal called for one common pinned Brave
toolchain, enforced egress and worker-only source/scratch, with independent
negative tests. It was a proposal, not an automatic contract amendment or coding
readiness approval. Later qualification is recorded separately.

[Report index](README.md) · [Methods and publication scope](METHODS.md)
