# Working browser versus frozen contract

Historical outcome: DEVIATION. The existing Python/Playwright script launched
native Brave explicitly in headless mode with sandboxing and an ephemeral profile.
A local data-page smoke verified the expected marker and separate-context cookie
isolation. The original environment had previously passed ten independent checks.

Kolibri itself completed five real browser MCP calls in Kilo: inspect tabs, open,
navigate to a harmless local page, inspect its content and close the tab. This
demonstrated agent tool access, beyond a coordinator-issued Python smoke test.

Nevertheless, the frozen contract required a hash-pinned Chromium installation.
The existing MCP setup also lacked verified documentation-origin restriction and
service-worker blocking. Headless mode and temporary profiles did not establish
network or worker filesystem isolation. A new common Brave contract and separate
boundary qualification were required; no silent substitution was approved by
this diagnostic. No installation or candidate development was performed.

[Report index](README.md) · [Methods and publication scope](METHODS.md)
