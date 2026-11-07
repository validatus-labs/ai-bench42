# Isolated model-to-browser proof and follow-up failure

Historical outcome: DEVIATION. A new exact-source offline assignment was checked
separately from the older browser baseline. A restricted Unix-socket inference
bridge connected the isolated Kilo worker to the existing Kolibri server. It
used a fixed destination, bounded requests/streams and method, path and model allowlists;
it was not a general HTTP proxy.

A real Kolibri generation issued four completed MCP calls: open a tab, navigate
to a harmless local data page, read its heading and close the tab. The recorded
tool calls came from the model, not the coordinator. A separate direct transport
probe made the total two actual model requests for this diagnostic.

Kilo's automatic follow-up was then rejected before inference: the bridge
mistakenly limited history to three calls although four calls used three distinct
tools. Ten offline transport/policy tests passed after correcting that bound.
A clean post-fix live continuation was not demonstrated in this record.

Independent review confirmed the capability and bounded isolation scope, including
file/network negatives. Actual Owner-visible extension attachment remained a
separate gate. The proof did not start C01–C07, qualify other models or approve
held-out evaluation.

[Report index](README.md) · [Methods and publication scope](METHODS.md)
