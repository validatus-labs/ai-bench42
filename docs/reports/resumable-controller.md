# Resuming experiments without replaying uncertain work

The controller checkpoints numbered attempts and phase status. Identical completed
inputs trigger verification/reuse; changed inputs need a new experiment identity.
Partial or uncertain inference/coding actions stop for review rather than spending
another trial budget automatically. A running job is not submitted twice.

Native qualification passed 189 coordinator, deployment and lifecycle regressions.
Existing-host inventory, adoption and observational checks passed with P1–P4
explicitly disabled. The resulting controller-only report correctly said PARTIAL,
not benchmark PASS. An identical repeat and offline report regeneration preserved
39 run files, including bytes, permissions and timestamps, without inference.

An earlier attempt exposed nondeterministic HTML metric ordering after JSON reload.
The rendering fix was verified separately; the failed original remained preserved.
The scope does not promise arbitrary power-loss recovery or safe replay of an
unknown model request. Fresh-host setup, SWE, visible-worker and Gold qualification
remained separate gates at this checkpoint.

[Report index](README.md) · [Methods and publication scope](METHODS.md)
