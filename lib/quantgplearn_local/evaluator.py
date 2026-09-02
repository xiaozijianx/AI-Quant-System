"""Program evaluation utilities for the GPU QuantGplearn path."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import torch

from .tensor_fitness import TensorFitness, clean_factor, normalize_by_day


@dataclass
class ProgramEvaluator:
    """Evaluate GP programs against TensorPanelData on one device."""

    data: object
    metric: TensorFitness
    transformer: Optional[object] = None
    cache_scores: bool = True
    cache_factors: bool = False
    normalize: bool = True
    clip: float = 1e6
    score_cache: dict[str, float] = field(default_factory=dict)
    factor_cache: dict[str, torch.Tensor] = field(default_factory=dict)

    @torch.no_grad()
    def evaluate_factor(self, program):
        key = program.generate_my_output()
        if self.cache_factors and key in self.factor_cache:
            return self.factor_cache[key]
        factor = program.execute_tensor(self.data)
        if self.transformer is not None:
            if hasattr(self.transformer, "call_torch"):
                factor = self.transformer.call_torch(factor)
            else:
                factor = self.transformer(factor)
        factor = clean_factor(factor, self.data.mask, clip=self.clip)
        if self.normalize:
            factor = normalize_by_day(factor, self.data.mask)
        if self.cache_factors:
            self.factor_cache[key] = factor.detach()
        return factor

    @torch.no_grad()
    def evaluate(self, program) -> float:
        key = program.generate_my_output()
        if self.cache_scores and key in self.score_cache:
            return self.score_cache[key]
        if self.data.target is None:
            raise ValueError("TensorPanelData.target is required for evaluation")
        try:
            pred = self.evaluate_factor(program)
            score = self.metric(self.data.target, pred, data=self.data)
        except Exception:
            score = 0.0
        if not np.isfinite(score):
            score = 0.0
        score = float(score)
        if self.cache_scores:
            self.score_cache[key] = score
        return score

    @torch.no_grad()
    def evaluate_population(self, population):
        for program in population:
            program.raw_fitness_ = self.evaluate(program)
        return population
