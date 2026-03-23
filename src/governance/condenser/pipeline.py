# src/governance/condenser/pipeline.py
"""Chain multiple condensers into a pipeline."""
from .base import Condenser, View


class CondenserPipeline(Condenser):
    def __init__(self, condensers: list[Condenser]):
        self.condensers = condensers

    def condense(self, view: View) -> View:
        for c in self.condensers:
            view = c.condense(view)
        return view
