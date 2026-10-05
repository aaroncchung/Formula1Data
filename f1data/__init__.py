"""Formula 1 data plane.

Two stages, kept apart on purpose (docs/architecture-review-findings.md,
section 6, rule 4):

* ``fetch`` copies a session from F1's timing archive into a source archive.
  It is the only stage that needs a network F1 answers.
* ``build`` reads that archive and publishes artifacts. It never contacts F1.
"""
