"""Analysis functions that operate on normalized session data.

This package is the single home for the analysis layer: the FastAPI service
imports it as ``app.analysis.*`` (the backend image sets ``WORKDIR /app`` and
copies ``backend/app`` to ``/app/app``), while the static artifact pipeline
imports the same files as ``backend.app.analysis.*`` from the repository root.
Both roots resolve to the same source; there is deliberately no second copy.

Because the package is loaded under two names, the modules here must stay
*root-agnostic*:

* import siblings **relatively** (``from .common import clean_laps``) so the
  import resolves under either root;
* do not import anything outside ``app.analysis`` -- in particular not
  ``app.models``, which only resolves when ``backend/`` is on ``sys.path``.

The consequence is that every function here returns plain dictionaries. The
pipeline serialises those directly; the API wraps them in Pydantic models at
the route boundary (``app/api/routes/``).

``qualifying_delta``, ``telemetry_compare`` and ``tyre_degradation`` are the
exceptions: they are API-only, are never imported by the pipeline, and so may
still reference ``app.models``.
"""
