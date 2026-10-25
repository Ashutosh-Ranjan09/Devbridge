"""M6 submodule 6.3 — scoring engine.

Observation model, Kalman update, decay kernel, recompute-from-log, read-time
propagation. Reproduces contracts/reference/m6_model.py exactly, but reads every
constant from contracts/m6-parameters.yaml instead of hard-coding it.

    from m6_scoring import ScoringEngine
    engine = ScoringEngine()
    state  = engine.fold(events, "typescript", as_of=date(2026, 8, 24))
    print(engine.explain(state))

No trained models. No optimiser. No labelled data. Closed-form updates only.
"""
__version__ = "1.0.0"

from .engine import Contribution, ScoringEngine, SkillState
from .errors import ParameterMismatch, ScoringError, UnscoreableEvent
from .filter import Filter, State, logit, sigmoid
from .observation import ObservationModel, interpolate
from .params import Parameters, Sweepable, default_parameters
from .propagation import Propagator, edges_from_ontology

__all__ = ["ScoringEngine", "SkillState", "Contribution", "Filter", "State",
           "ObservationModel", "Propagator", "edges_from_ontology", "Parameters",
           "Sweepable", "default_parameters", "interpolate", "logit", "sigmoid",
           "ScoringError", "UnscoreableEvent", "ParameterMismatch", "__version__"]
