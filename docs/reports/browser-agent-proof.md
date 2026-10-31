# A real browser task through Kolibri and Kilo

The browser test used native Brave, Playwright MCP and the installed Kilo harness.
Direct automation, Kolibri-to-MCP and Kilo-to-Kolibri-to-MCP each completed a local
form interaction. A fresh code on the page had to be read and submitted before
the test server generated a receipt. This checked actual interaction rather than
a plausible textual description.

The Kilo case completed nine browser calls. Explicit High reasoning was used in
the separate model/MCP test; the GUI selector's mapping was not instrumented.
Renderer namespace/seccomp state and sandbox status were observed, in addition
to launch flags. No additional host security profile was needed for this test.

Earlier unsandboxed attempts remain historical failures/limitations, not part of
this accepted sandboxed case. Browser sandboxing does not establish worker file
isolation or network egress control. The test qualifies a small local workflow,
not arbitrary websites, authenticated browsing or long coding reliability.

[Report index](README.md) · [Methods and publication scope](METHODS.md)
