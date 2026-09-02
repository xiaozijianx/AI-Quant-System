"""GPU-enabled symbolic factor mining for QuantGplearn.

This module keeps QuantGplearn's GP tree representation and genetic operators,
but replaces the expensive Pandas/groupby execution path with a dense
Tensor/PyTorch evaluator inspired by alphagen's Calculator/Pool design.
"""
from __future__ import annotations

import datetime as _dt
import itertools
from copy import deepcopy
from time import time
from typing import Iterable, Optional, Sequence
from warnings import warn

import numpy as np
import pandas as pd
import torch
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.exceptions import NotFittedError

from ._program import _Program
from .functions import _Function, _function_map, sig1 as sigmoid
from .tensor_data import TensorPanelData
from .tensor_fitness import get_tensor_fitness, batch_pearsonr
from .torch_functions import GPU_SAFE_PANEL_FUNCTIONS, register_torch_functions
from .evaluator import ProgramEvaluator
from .utils import check_random_state

MAX_INT = np.iinfo(np.int32).max


def _resolve_device(device: str | torch.device) -> torch.device:
    dev = torch.device(device)
    if dev.type == "cuda" and not torch.cuda.is_available():
        warn("CUDA is not available; falling back to CPU tensor execution.")
        dev = torch.device("cpu")
    return dev


def _build_function_dict(function_set, const_range):
    register_torch_functions()
    function_dict = {"number": [], "category": []}
    unsupported = []
    for function in function_set:
        if isinstance(function, str):
            if function not in _function_map:
                raise ValueError(f"invalid function name {function!r} found in function_set")
            function = deepcopy(_function_map[function])
        elif isinstance(function, _Function):
            function = deepcopy(function)
        else:
            raise ValueError(f"invalid function type {type(function)} found in function_set")
        function.add_range(const_range)
        if getattr(function, "torch_function", None) is None:
            unsupported.append(function.name)
            continue
        if function.return_type == "number":
            function_dict["number"].append(function)
        else:
            function_dict["category"].append(function)
    if unsupported:
        raise ValueError(
            "The GPU backend does not yet support these functions: "
            f"{sorted(set(unsupported))}. Use GPU_SAFE_PANEL_FUNCTIONS or add torch backends."
        )
    if not function_dict["number"]:
        raise ValueError("No GPU-supported numeric functions found in function_set")
    arities = {}
    for f in function_dict["number"] + function_dict["category"]:
        arities.setdefault(f.arity, []).append(f)
    return function_dict, arities


def _method_cumsum(p_crossover, p_subtree_mutation, p_hoist_mutation, p_point_mutation):
    probs = np.array([p_crossover, p_subtree_mutation, p_hoist_mutation, p_point_mutation], dtype=float)
    cumsum = np.cumsum(probs)
    if cumsum[-1] > 1.0:
        raise ValueError("The sum of genetic-operation probabilities must be <= 1.0")
    return cumsum


def _generate_population(
    n_programs: int,
    parents,
    seeds,
    params: dict,
    max_length: int,
):
    """Generate offspring programs without evaluating fitness."""
    programs = []
    tournament_size = params["tournament_size"]
    method_probs = params["method_probs"]
    metric = params["metric"]

    def tournament(random_state):
        contenders = random_state.randint(0, len(parents), tournament_size)
        fitness = [parents[p].fitness_ for p in contenders]
        if metric.greater_is_better:
            parent_index = contenders[int(np.argmax(fitness))]
        else:
            parent_index = contenders[int(np.argmin(fitness))]
        return parents[parent_index], int(parent_index)

    for i in range(n_programs):
        random_state = check_random_state(seeds[i])
        if parents is None:
            program_nodes = None
            genome = None
        else:
            method = random_state.uniform()
            parent, parent_index = tournament(random_state)
            if parent.length_ <= max_length:
                if method < method_probs[0]:
                    donor, donor_index = tournament(random_state)
                    program_nodes, removed, remains = parent.crossover(donor.program, random_state)
                    genome = {
                        "method": "Crossover",
                        "parent_idx": parent_index,
                        "parent_nodes": removed,
                        "donor_idx": donor_index,
                        "donor_nodes": remains,
                    }
                elif method < method_probs[1]:
                    program_nodes, removed, _ = parent.subtree_mutation(random_state)
                    genome = {"method": "Subtree Mutation", "parent_idx": parent_index, "parent_nodes": removed}
                elif method < method_probs[2]:
                    program_nodes, removed = parent.hoist_mutation(random_state)
                    genome = {"method": "Hoist Mutation", "parent_idx": parent_index, "parent_nodes": removed}
                elif method < method_probs[3]:
                    program_nodes, mutated = parent.point_mutation(random_state)
                    genome = {"method": "Point Mutation", "parent_idx": parent_index, "parent_nodes": mutated}
                else:
                    program_nodes = parent.reproduce()
                    genome = {"method": "Reproduction", "parent_idx": parent_index, "parent_nodes": []}
            else:
                program_nodes = parent.reproduce()
                genome = {"method": "Reproduction", "parent_idx": parent_index, "parent_nodes": []}

        program = _Program(
            function_dict=params["function_dict"],
            arities=params["arities"],
            init_depth=params["init_depth"],
            init_method=params["init_method"],
            n_features=params["n_features"],
            const_range=params["const_range"],
            metric=metric,
            transformer=params.get("transformer"),
            p_point_replace=params["p_point_replace"],
            parsimony_coefficient=params["parsimony_coefficient"],
            data_type="panel",
            feature_names=params.get("feature_names"),
            random_state=random_state,
            n_cat_features=0,
            program=program_nodes,
        )
        program.parents = genome
        programs.append(program)
    return programs


class GpuSymbolicTransformer(BaseEstimator, TransformerMixin):
    """Symbolic factor miner with Tensor/PyTorch execution.

    The class is intended for panel factor mining. Input data should be a
    DataFrame indexed by ``[time_series_index, security_index]`` or contain
    these two columns. Features are converted to a dense tensor ``[T, N, F]``.
    """

    def __init__(
        self,
        *,
        population_size: int = 1000,
        hall_of_fame: int = 100,
        n_components: int = 10,
        generations: int = 20,
        tournament_size: int = 20,
        stopping_criteria: float = 1.0,
        const_range=(-1.0, 1.0),
        init_depth=(2, 6),
        init_method: str = "half and half",
        function_set: Sequence[str] | None = None,
        objective: str = "icir",
        metric: str | None = None,
        transformer=None,
        parsimony_coefficient: float | str = 0.001,
        p_crossover: float = 0.5,
        p_subtree_mutation: float = 0.2,
        p_hoist_mutation: float = 0.1,
        p_point_mutation: float = 0.1,
        p_point_replace: float = 0.05,
        max_samples: float = 1.0,
        max_length: int = 24,
        tolerable_corr: float | None = 0.7,
        feature_names: Optional[Sequence[str]] = None,
        time_series_index: str = "datetime",
        security_index: str = "symbol",
        device: str = "cuda",
        dtype: torch.dtype = torch.float32,
        normalize: bool = True,
        cache_scores: bool = True,
        cache_factors: bool = False,
        warm_start: bool = False,
        low_memory: bool = True,
        n_jobs: int = 1,
        verbose: int = 0,
        random_state=None,
    ):
        self.population_size = population_size
        self.hall_of_fame = hall_of_fame
        self.n_components = n_components
        self.generations = generations
        self.tournament_size = tournament_size
        self.stopping_criteria = stopping_criteria
        self.const_range = const_range
        self.init_depth = init_depth
        self.init_method = init_method
        self.function_set = function_set
        self.objective = objective
        self.metric = metric
        self.transformer = transformer
        self.parsimony_coefficient = parsimony_coefficient
        self.p_crossover = p_crossover
        self.p_subtree_mutation = p_subtree_mutation
        self.p_hoist_mutation = p_hoist_mutation
        self.p_point_mutation = p_point_mutation
        self.p_point_replace = p_point_replace
        self.max_samples = max_samples
        self.max_length = max_length
        self.tolerable_corr = tolerable_corr
        self.feature_names = None if feature_names is None else list(feature_names)
        self.time_series_index = time_series_index
        self.security_index = security_index
        self.device = device
        self.dtype = dtype
        self.normalize = normalize
        self.cache_scores = cache_scores
        self.cache_factors = cache_factors
        self.warm_start = warm_start
        self.low_memory = low_memory
        self.n_jobs = n_jobs
        self.verbose = verbose
        self.random_state = random_state

    def __len__(self):
        if not hasattr(self, "_best_programs"):
            return 0
        return len(self._best_programs)

    def __iter__(self):
        if not hasattr(self, "_best_programs"):
            raise NotFittedError("GpuSymbolicTransformer not fitted.")
        return iter(self._best_programs)

    def __getitem__(self, item):
        if not hasattr(self, "_best_programs"):
            raise NotFittedError("GpuSymbolicTransformer not fitted.")
        return self._best_programs[item]

    def __str__(self):
        if not hasattr(self, "_best_programs"):
            return self.__repr__()
        output = str([gp.__str__() for gp in self._best_programs])
        return output.replace("',", ",\n").replace("'", "")

    def _prepare_metric(self):
        name = self.metric if self.metric is not None else self.objective
        return get_tensor_fitness(name)

    def _prepare_transformer(self):
        if self.transformer is None:
            return None
        if isinstance(self.transformer, _Function):
            return deepcopy(self.transformer)
        if self.transformer == "sigmoid":
            f = deepcopy(sigmoid)
            # sigmoid receives one vector and is supported by torch_functions as 'sig'
            f.torch_function = _function_map["sig"].torch_function
            return f
        raise ValueError("transformer must be None, 'sigmoid' or a _Function")

    def _initialize(self, data: TensorPanelData):
        if self.hall_of_fame is None:
            self.hall_of_fame_ = self.population_size
        else:
            self.hall_of_fame_ = int(self.hall_of_fame)
        if self.hall_of_fame_ > self.population_size or self.hall_of_fame_ < 1:
            raise ValueError("hall_of_fame must be in [1, population_size]")
        self.n_components_ = int(self.n_components if self.n_components is not None else self.hall_of_fame_)
        if self.n_components_ > self.hall_of_fame_ or self.n_components_ < 1:
            raise ValueError("n_components must be in [1, hall_of_fame]")
        if self.init_method not in ("half and half", "grow", "full"):
            raise ValueError("init_method must be 'half and half', 'grow' or 'full'")
        if not isinstance(self.init_depth, tuple) or len(self.init_depth) != 2 or self.init_depth[0] > self.init_depth[1]:
            raise ValueError("init_depth must be a two-item increasing tuple")
        self._metric = self._prepare_metric()
        self._transformer = self._prepare_transformer()
        function_set = self.function_set if self.function_set is not None else GPU_SAFE_PANEL_FUNCTIONS
        self._function_dict, self._arities = _build_function_dict(function_set, self.const_range)
        self._method_probs = _method_cumsum(
            self.p_crossover,
            self.p_subtree_mutation,
            self.p_hoist_mutation,
            self.p_point_mutation,
        )
        self.n_features_in_ = data.n_features
        self.feature_names_ = list(data.feature_names)
        self.device_ = data.device
        self.dtype_ = data.dtype
        self.evaluator_ = ProgramEvaluator(
            data=data,
            metric=self._metric,
            transformer=self._transformer,
            cache_scores=self.cache_scores,
            cache_factors=self.cache_factors,
            normalize=self.normalize,
        )
        if not self.warm_start or not hasattr(self, "_programs"):
            self._programs = []
            self.run_details_ = {
                "generation": [],
                "average_length": [],
                "average_fitness": [],
                "best_length": [],
                "best_fitness": [],
                "generation_time": [],
            }

    def _params_for_programs(self):
        return {
            "tournament_size": self.tournament_size,
            "function_dict": self._function_dict,
            "arities": self._arities,
            "init_depth": self.init_depth,
            "init_method": self.init_method,
            "const_range": self.const_range,
            "metric": self._metric,
            "transformer": self._transformer,
            "parsimony_coefficient": self.parsimony_coefficient,
            "method_probs": self._method_probs,
            "p_point_replace": self.p_point_replace,
            "feature_names": self.feature_names_,
            "n_features": self.n_features_in_,
        }

    def fit_panel(self, X: pd.DataFrame, target_col: str = "target", y=None, max_length: Optional[int] = None):
        """Fit on panel data and a target column or external target vector."""
        if self.feature_names is None:
            excluded = {target_col, self.time_series_index, self.security_index}
            self.feature_names = [c for c in X.columns if c not in excluded]
        device = _resolve_device(self.device)
        data = TensorPanelData.from_panel_df(
            X,
            feature_names=self.feature_names,
            target_col=target_col if y is None else None,
            y=y,
            time_index=self.time_series_index,
            security_index=self.security_index,
            device=str(device),
            dtype=self.dtype,
        )
        self.tensor_data_ = data
        self._initialize(data)
        return self._fit_tensor(data, max_length=max_length or self.max_length)

    def fit(self, X, y=None, max_length: Optional[int] = None):
        """sklearn-compatible fit. For panel DataFrames, prefer fit_panel."""
        if y is None:
            target_col = "target"
            if not isinstance(X, pd.DataFrame) or target_col not in X.columns:
                raise ValueError("fit requires either y or a DataFrame with a 'target' column")
            return self.fit_panel(X, target_col=target_col, max_length=max_length)
        return self.fit_panel(X, y=y, target_col="target", max_length=max_length)

    def _fit_tensor(self, data: TensorPanelData, max_length: int):
        random_state = check_random_state(self.random_state)
        prior_generations = len(self._programs)
        if self.warm_start:
            for _ in range(prior_generations):
                random_state.randint(MAX_INT, size=self.population_size)
        elif prior_generations:
            self._programs = []
            prior_generations = 0

        if self.verbose:
            print("    gen | avg_len | avg_fit | best_len | best_fit | seconds")

        params = self._params_for_programs()
        fitness = None
        for gen in range(prior_generations, self.generations):
            start = time()
            parents = None if gen == 0 else self._programs[gen - 1]
            seeds = random_state.randint(MAX_INT, size=self.population_size)
            population = _generate_population(
                n_programs=self.population_size,
                parents=parents,
                seeds=seeds,
                params=params,
                max_length=max_length,
            )
            self.evaluator_.evaluate_population(population)

            raw_fitness = np.array([p.raw_fitness_ for p in population], dtype=float)
            length = np.array([p.length_ for p in population], dtype=float)
            adjusted = raw_fitness - (1.01 ** length - 1.0)

            if self.parsimony_coefficient == "auto":
                denom = np.var(length)
                parsimony = 0.0 if denom <= 0 else float(np.cov(length, adjusted)[1, 0] / denom)
            else:
                parsimony = float(self.parsimony_coefficient or 0.0)
            for p in population:
                p.fitness_ = p.fitness(parsimony)

            fitness = np.array([p.fitness_ for p in population], dtype=float)
            best_idx = int(np.argmax(fitness) if self._metric.greater_is_better else np.argmin(fitness))
            best_program = population[best_idx]
            elapsed = time() - start
            self.run_details_["generation"].append(gen)
            self.run_details_["average_length"].append(float(np.mean(length)))
            self.run_details_["average_fitness"].append(float(np.mean(raw_fitness)))
            self.run_details_["best_length"].append(int(best_program.length_))
            self.run_details_["best_fitness"].append(float(best_program.raw_fitness_))
            self.run_details_["generation_time"].append(float(elapsed))
            if self.verbose:
                print(
                    f"{gen:7d} | {np.mean(length):7.2f} | {np.mean(raw_fitness):7.4f} | "
                    f"{best_program.length_:8d} | {best_program.raw_fitness_:8.4f} | {elapsed:7.2f}"
                )

            self._programs.append(population)
            if self.low_memory and gen > 0:
                self._programs[gen - 1] = None

            threshold_score = best_program.raw_fitness_
            if self._metric.greater_is_better and threshold_score >= self.stopping_criteria:
                if self.verbose:
                    print(f"{_dt.datetime.now()} early stop: {threshold_score} >= {self.stopping_criteria}")
                break

        if not self._programs or self._programs[-1] is None:
            raise RuntimeError("No final population is available")
        self._select_best_programs(self._programs[-1])
        return self

    @torch.no_grad()
    def _select_best_programs(self, population):
        raw = np.array([p.raw_fitness_ for p in population], dtype=float)
        order = raw.argsort()[::-1] if self._metric.greater_is_better else raw.argsort()
        hof_indices = order[: self.hall_of_fame_]
        candidates = [population[i] for i in hof_indices]

        selected = []
        selected_factors = []
        threshold = self.tolerable_corr
        for program in candidates:
            if len(selected) >= self.n_components_:
                break
            if threshold is not None and selected:
                f = self.evaluator_.evaluate_factor(program)
                ok = True
                for old_f in selected_factors:
                    corr = batch_pearsonr(f, old_f, self.tensor_data_.mask)
                    mutual = torch.nanmean(torch.abs(corr))
                    if torch.isfinite(mutual) and float(mutual.item()) > float(threshold):
                        ok = False
                        break
                if not ok:
                    continue
                selected_factors.append(f)
            else:
                if threshold is not None:
                    selected_factors.append(self.evaluator_.evaluate_factor(program))
            selected.append(program)

        if len(selected) < self.n_components_:
            # Fill with the best remaining candidates to avoid returning too few factors.
            for program in candidates:
                if len(selected) >= self.n_components_:
                    break
                if program not in selected:
                    selected.append(program)
        self._best_programs = selected[: self.n_components_]
        self._best_scores = [float(p.raw_fitness_) for p in self._best_programs]

    @torch.no_grad()
    def transform_panel(self, X: Optional[pd.DataFrame] = None, output: str = "dataframe"):
        """Transform panel data into mined factors.

        If ``X`` is None, transform the training panel. If ``output`` is
        ``'tensor'`` return a list of ``[T, N]`` tensors; otherwise return a
        long panel DataFrame with one column per factor.
        """
        if not hasattr(self, "_best_programs"):
            raise NotFittedError("GpuSymbolicTransformer not fitted.")
        if X is None:
            data = self.tensor_data_
        else:
            device = _resolve_device(self.device)
            data = TensorPanelData.from_panel_df(
                X,
                feature_names=self.feature_names_,
                target_col=None,
                time_index=self.time_series_index,
                security_index=self.security_index,
                device=str(device),
                dtype=self.dtype,
            )
        factors = []
        for p in self._best_programs:
            if X is None:
                f = self.evaluator_.evaluate_factor(p)
            else:
                ev = ProgramEvaluator(data, self._metric, transformer=self._transformer, normalize=self.normalize)
                f = ev.evaluate_factor(p)
            factors.append(f)
        if output == "tensor":
            return factors
        if output == "numpy":
            return np.stack([f.detach().cpu().numpy().reshape(-1) for f in factors], axis=1)
        names = [f"factor_{i:03d}" for i in range(len(factors))]
        return data.factors_to_dataframe(factors, names=names)

    def transform(self, X=None):
        return self.transform_panel(X, output="numpy")

    def fit_transform(self, X, y=None, max_length: Optional[int] = None):
        return self.fit(X, y=y, max_length=max_length).transform(X)

    def get_factor_expressions(self) -> pd.DataFrame:
        if not hasattr(self, "_best_programs"):
            raise NotFittedError("GpuSymbolicTransformer not fitted.")
        return pd.DataFrame(
            {
                "rank": np.arange(1, len(self._best_programs) + 1),
                "score": self._best_scores,
                "expression": [p.generate_my_output() for p in self._best_programs],
                "length": [p.length_ for p in self._best_programs],
                "depth": [p.depth_ for p in self._best_programs],
            }
        )
