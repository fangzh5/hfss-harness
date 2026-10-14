import copy
import math
from typing import List

import numpy as np

from .base import OptimizationAlgorithm


class NSGA2Optimizer(OptimizationAlgorithm):
    """NSGA-II optimizer for Pareto-based multi-objective search."""

    def __init__(
        self,
        bounds: List[tuple],
        pop_size: int = 40,
        crossover_prob: float = 0.9,
        mutation_prob: float | None = None,
        eta_c: float = 15.0,
        eta_m: float = 20.0,
        initial_population: np.ndarray | None = None,
        constraint_strategy: str = "constraint_domination",
    ):
        super().__init__(bounds, pop_size)
        self.pop_size = int(pop_size)
        self.n_dims = len(bounds)
        self.crossover_prob = float(crossover_prob)
        self.mutation_prob = (
            float(mutation_prob)
            if mutation_prob is not None
            else max(1.0 / max(self.n_dims, 1), 0.05)
        )
        self.eta_c = float(eta_c)
        self.eta_m = float(eta_m)
        self.constraint_strategy = self._normalize_constraint_strategy(constraint_strategy)

        self.population = self._init_population(initial_population)
        self.offspring_population = self.population.copy()

        self.objectives = None
        self.constraint_violations = None
        self.source_sim_ids = np.full(self.pop_size, -1, dtype=int)
        self.valid_individuals = np.zeros(self.pop_size, dtype=bool)
        self.ranks = np.full(self.pop_size, np.inf)
        self.crowding = np.zeros(self.pop_size, dtype=float)

        self.pareto_indices = np.array([], dtype=int)
        self.pareto_front: list[dict] = []
        self.last_front_updated = False
        self.last_representative_improved = False
        self.best_result = None
        self.best_source_sim_id = None
        self._evaluated_records = []

    def _init_population(self, initial_population: np.ndarray | None = None) -> np.ndarray:
        if initial_population is not None:
            pop = np.asarray(initial_population, dtype=float)
            if pop.shape == (self.pop_size, self.n_dims):
                clipped = pop.copy()
                for dim, (low, high) in enumerate(self.bounds):
                    clipped[:, dim] = np.clip(clipped[:, dim], low, high)
                return clipped

        population = np.zeros((self.pop_size, self.n_dims), dtype=float)
        for dim, (low, high) in enumerate(self.bounds):
            population[:, dim] = np.random.uniform(low, high, self.pop_size)
        return population

    @property
    def is_multi_objective(self) -> bool:
        return True

    @property
    def name(self) -> str:
        return "NSGA-II"

    def suggest(self) -> np.ndarray:
        if self.best_params is not None:
            return self.best_params.copy()
        return self.offspring_population[0].copy()

    def suggest_population(self) -> np.ndarray:
        return self.offspring_population.copy()

    def _extract_batch(self, fitness_results: List):
        params = np.zeros((self.pop_size, self.n_dims), dtype=float)
        objectives = []
        constraint_violations = np.zeros(self.pop_size, dtype=float)
        source_sim_ids = np.full(self.pop_size, -1, dtype=int)
        by_idx = {}
        for result in fitness_results:
            idx = getattr(result, "individual_idx", None)
            if idx is None or idx >= self.pop_size:
                continue
            if not hasattr(result, "params"):
                continue
            params[idx] = np.asarray(result.params, dtype=float)
            objectives.append(np.asarray(getattr(result, "objectives", []), dtype=float))
            constraint_violations[idx] = float(getattr(result, "constraint_violation", 0.0))
            source_sim_ids[idx] = int(getattr(result, "source_sim_id", -1) or -1)
            if not getattr(result, "valid", True):
                # Internal only: every valid, finite violation dominates an invalid solve.
                constraint_violations[idx] = np.inf
                source_sim_ids[idx] = -1
            by_idx[idx] = result

        if len(by_idx) != self.pop_size:
            raise RuntimeError(
                f"NSGA-II expects {self.pop_size} evaluated individuals, got {len(by_idx)}."
            )

        ordered_objectives = np.vstack(
            [np.asarray(getattr(by_idx[idx], "objectives", []), dtype=float) for idx in range(self.pop_size)]
        )
        return params, ordered_objectives, constraint_violations, source_sim_ids, by_idx

    @staticmethod
    def _normalize_constraint_strategy(strategy: str) -> str:
        normalized = str(strategy or "constraint_domination").strip().lower().replace("-", "_")
        aliases = {
            "constraint_domination": "constraint_domination",
            "s11_feasible_first": "constraint_domination",
            "feasible_first": "constraint_domination",
            "lexicographic_feasible_first": "lexicographic_feasible_first",
            "lexicographic": "lexicographic_feasible_first",
        }
        return aliases.get(normalized, "constraint_domination")

    @staticmethod
    def _lexicographic_better(obj_a, obj_b, atol: float = 1e-12) -> bool:
        for a, b in zip(np.asarray(obj_a, dtype=float), np.asarray(obj_b, dtype=float)):
            if a < b - atol:
                return True
            if a > b + atol:
                return False
        return False

    def _dominates(self, obj_a, cv_a: float, obj_b, cv_b: float) -> bool:
        if cv_a <= 1e-12 and cv_b > 1e-12:
            return True
        if cv_a > 1e-12 and cv_b <= 1e-12:
            return False
        if cv_a > 1e-12 and cv_b > 1e-12:
            return cv_a < cv_b
        if self.constraint_strategy == "lexicographic_feasible_first":
            return self._lexicographic_better(obj_a, obj_b)
        return np.all(obj_a <= obj_b) and np.any(obj_a < obj_b)

    def _fast_non_dominated_sort(self, objectives: np.ndarray, constraint_violations: np.ndarray) -> list[list[int]]:
        n = len(objectives)
        dominates = [[] for _ in range(n)]
        dominated_count = np.zeros(n, dtype=int)
        fronts: list[list[int]] = [[]]

        for p in range(n):
            for q in range(n):
                if p == q:
                    continue
                if self._dominates(objectives[p], constraint_violations[p], objectives[q], constraint_violations[q]):
                    dominates[p].append(q)
                elif self._dominates(objectives[q], constraint_violations[q], objectives[p], constraint_violations[p]):
                    dominated_count[p] += 1
            if dominated_count[p] == 0:
                fronts[0].append(p)

        i = 0
        while i < len(fronts) and fronts[i]:
            next_front = []
            for p in fronts[i]:
                for q in dominates[p]:
                    dominated_count[q] -= 1
                    if dominated_count[q] == 0:
                        next_front.append(q)
            if next_front:
                fronts.append(next_front)
            i += 1
        return fronts

    @staticmethod
    def _crowding_distance(front_indices: list[int], objectives: np.ndarray) -> np.ndarray:
        if not front_indices:
            return np.array([], dtype=float)

        num_objectives = objectives.shape[1]
        crowding = np.zeros(len(front_indices), dtype=float)
        front_values = objectives[front_indices]

        if len(front_indices) <= 2:
            crowding[:] = np.inf
            return crowding

        for m in range(num_objectives):
            order = np.argsort(front_values[:, m])
            crowding[order[0]] = np.inf
            crowding[order[-1]] = np.inf
            min_val = front_values[order[0], m]
            max_val = front_values[order[-1], m]
            span = max(max_val - min_val, 1e-12)
            for pos in range(1, len(order) - 1):
                if np.isinf(crowding[order[pos]]):
                    continue
                prev_val = front_values[order[pos - 1], m]
                next_val = front_values[order[pos + 1], m]
                crowding[order[pos]] += (next_val - prev_val) / span
        return crowding

    def _select_next_generation(
        self,
        population: np.ndarray,
        objectives: np.ndarray,
        constraint_violations: np.ndarray,
        source_sim_ids: np.ndarray,
        result_records: list,
    ):
        fronts = self._fast_non_dominated_sort(objectives, constraint_violations)
        selected_indices: list[int] = []
        ranks = np.full(len(population), np.inf)
        crowding = np.zeros(len(population), dtype=float)

        for rank, front in enumerate(fronts):
            if not front:
                continue
            for idx in front:
                ranks[idx] = rank

            distances = self._crowding_distance(front, objectives)
            for local_idx, global_idx in enumerate(front):
                crowding[global_idx] = distances[local_idx]

            remaining = self.pop_size - len(selected_indices)
            if remaining <= 0:
                break
            if len(front) <= remaining:
                selected_indices.extend(front)
                continue

            sorted_front = sorted(
                front,
                key=lambda idx: crowding[idx],
                reverse=True,
            )
            selected_indices.extend(sorted_front[:remaining])
            break

        selected_indices = np.asarray(selected_indices[: self.pop_size], dtype=int)
        self.population = population[selected_indices].copy()
        self.objectives = objectives[selected_indices].copy()
        self.constraint_violations = constraint_violations[selected_indices].copy()
        self.source_sim_ids = source_sim_ids[selected_indices].copy()
        self.ranks = ranks[selected_indices].copy()
        self.crowding = crowding[selected_indices].copy()

        selected_records = [result_records[idx] for idx in selected_indices]
        self.valid_individuals = np.asarray([getattr(record, "valid", True) for record in selected_records], dtype=bool)
        for local_idx, record in enumerate(selected_records):
            record.rank = int(self.ranks[local_idx])
            record.crowding_distance = float(self.crowding[local_idx])

        self._evaluated_records = copy.deepcopy(selected_records)

        self._update_pareto_front(selected_records)

    def _update_pareto_front(self, selected_records: list) -> None:
        front_indices = np.where((self.ranks == 0) & self.valid_individuals)[0]
        self.pareto_indices = front_indices
        self.pareto_front = []
        for idx in front_indices:
            record = selected_records[idx]
            self.pareto_front.append(self._front_record(record))

        self.last_front_updated = len(self.pareto_front) > 0
        self._update_representative_best(selected_records)

    @staticmethod
    def _front_record(record):
        return {
            "params": np.asarray(record.params, dtype=float).tolist(),
            "objectives": np.asarray(record.objectives, dtype=float).tolist(),
            "constraint_violation": float(getattr(record, "constraint_violation", 0.0)),
            "rank": int(getattr(record, "rank", 0)),
            "crowding_distance": float(getattr(record, "crowding_distance", 0.0)),
            "source_sim_id": getattr(record, "source_sim_id", None),
        }

    def finalize_partial_batch(self, fitness_results: List) -> None:
        """Publish valid observations when stopping, without pretending to tell a full generation.

        Population and offspring remain unchanged. This is terminal result selection,
        not a continuation API. Full records retain metric/target/provenance fields.
        """
        records = [copy.deepcopy(record) for record in self._evaluated_records + list(fitness_results)
                   if getattr(record, "valid", True)]
        if not records:
            return
        objectives = np.asarray([record.objectives for record in records], dtype=float)
        violations = np.asarray([record.constraint_violation for record in records], dtype=float)
        fronts = self._fast_non_dominated_sort(objectives, violations)
        for rank, front in enumerate(fronts):
            distances = self._crowding_distance(front, objectives)
            for local_idx, index in enumerate(front):
                records[index].rank = rank
                records[index].crowding_distance = float(distances[local_idx])
        previous_front = self.pareto_front
        self.pareto_front = [self._front_record(records[index]) for index in fronts[0]]
        self.last_front_updated = previous_front != self.pareto_front
        self._update_representative_best(records)

    def _update_representative_best(self, selected_records: list) -> None:
        valid_indices = [idx for idx, record in enumerate(selected_records) if getattr(record, "valid", True)]
        if not valid_indices:
            self.last_representative_improved = False
            return

        def key(local_idx: int):
            record = selected_records[local_idx]
            objectives = np.asarray(getattr(record, "objectives", []), dtype=float)
            return (
                float(getattr(record, "constraint_violation", 0.0)),
                int(getattr(record, "rank", math.inf)),
                *objectives.tolist(),
                -float(getattr(record, "crowding_distance", 0.0)),
            )

        best_local_idx = min(valid_indices, key=key)
        best_record = selected_records[best_local_idx]
        representative_score = float(getattr(best_record, "constraint_violation", 0.0))
        if representative_score <= 1e-12:
            representative_score = float(np.sum(np.asarray(best_record.objectives, dtype=float)))

        improved = False
        if self.best_params is None or representative_score < self.best_cost - 1e-12:
            improved = True
        self.best_params = np.asarray(best_record.params, dtype=float).copy()
        self.best_cost = representative_score
        self.best_result = best_record
        self.best_source_sim_id = getattr(best_record, "source_sim_id", None)
        self.last_representative_improved = improved

    def _tournament_select(self) -> int:
        i, j = np.random.choice(self.pop_size, 2, replace=False)
        if self.ranks[i] < self.ranks[j]:
            return i
        if self.ranks[j] < self.ranks[i]:
            return j
        if self.crowding[i] > self.crowding[j]:
            return i
        if self.crowding[j] > self.crowding[i]:
            return j
        return int(np.random.choice([i, j]))

    def _sbx_crossover(self, parent1: np.ndarray, parent2: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        child1 = parent1.copy()
        child2 = parent2.copy()
        if np.random.random() > self.crossover_prob:
            return child1, child2

        for dim, (low, high) in enumerate(self.bounds):
            if np.random.random() > 0.5 or abs(parent1[dim] - parent2[dim]) < 1e-14:
                continue
            x1 = min(parent1[dim], parent2[dim])
            x2 = max(parent1[dim], parent2[dim])
            rand = np.random.random()

            beta = 1.0 + (2.0 * (x1 - low) / max(x2 - x1, 1e-12))
            alpha = 2.0 - beta ** (-(self.eta_c + 1.0))
            if rand <= 1.0 / alpha:
                betaq = (rand * alpha) ** (1.0 / (self.eta_c + 1.0))
            else:
                betaq = (1.0 / (2.0 - rand * alpha)) ** (1.0 / (self.eta_c + 1.0))
            c1 = 0.5 * ((x1 + x2) - betaq * (x2 - x1))

            beta = 1.0 + (2.0 * (high - x2) / max(x2 - x1, 1e-12))
            alpha = 2.0 - beta ** (-(self.eta_c + 1.0))
            if rand <= 1.0 / alpha:
                betaq = (rand * alpha) ** (1.0 / (self.eta_c + 1.0))
            else:
                betaq = (1.0 / (2.0 - rand * alpha)) ** (1.0 / (self.eta_c + 1.0))
            c2 = 0.5 * ((x1 + x2) + betaq * (x2 - x1))

            c1 = np.clip(c1, low, high)
            c2 = np.clip(c2, low, high)
            if np.random.random() <= 0.5:
                child1[dim], child2[dim] = c2, c1
            else:
                child1[dim], child2[dim] = c1, c2
        return child1, child2

    def _polynomial_mutation(self, individual: np.ndarray) -> np.ndarray:
        mutant = individual.copy()
        for dim, (low, high) in enumerate(self.bounds):
            if np.random.random() > self.mutation_prob:
                continue
            if high <= low:
                continue

            x = mutant[dim]
            delta1 = (x - low) / (high - low)
            delta2 = (high - x) / (high - low)
            rand = np.random.random()
            mut_pow = 1.0 / (self.eta_m + 1.0)

            if rand < 0.5:
                xy = 1.0 - delta1
                val = 2.0 * rand + (1.0 - 2.0 * rand) * (xy ** (self.eta_m + 1.0))
                deltaq = val ** mut_pow - 1.0
            else:
                xy = 1.0 - delta2
                val = 2.0 * (1.0 - rand) + 2.0 * (rand - 0.5) * (xy ** (self.eta_m + 1.0))
                deltaq = 1.0 - val ** mut_pow

            x = x + deltaq * (high - low)
            mutant[dim] = np.clip(x, low, high)
        return mutant

    def _make_offspring(self) -> np.ndarray:
        offspring = np.zeros_like(self.population)
        idx = 0
        while idx < self.pop_size:
            p1 = self.population[self._tournament_select()]
            p2 = self.population[self._tournament_select()]
            c1, c2 = self._sbx_crossover(p1, p2)
            offspring[idx] = self._polynomial_mutation(c1)
            if idx + 1 < self.pop_size:
                offspring[idx + 1] = self._polynomial_mutation(c2)
            idx += 2
        return offspring

    def update(self, fitness_results: List):
        offspring_params, offspring_objectives, offspring_cv, offspring_source_sim_ids, by_idx = self._extract_batch(fitness_results)
        offspring_records = [by_idx[idx] for idx in range(self.pop_size)]

        if self.objectives is None:
            self.population = offspring_params.copy()
            self.objectives = offspring_objectives.copy()
            self.constraint_violations = offspring_cv.copy()
            self.source_sim_ids = offspring_source_sim_ids.copy()
            self._select_next_generation(
                self.population,
                self.objectives,
                self.constraint_violations,
                self.source_sim_ids,
                offspring_records,
            )
            self.offspring_population = self._make_offspring()
            return

        parent_records = []
        for idx in range(self.pop_size):
            if len(self._evaluated_records) == self.pop_size:
                parent_records.append(copy.deepcopy(self._evaluated_records[idx]))
                continue
            parent_record = type("ParentRecord", (), {})()
            parent_record.params = self.population[idx].copy()
            parent_record.objectives = self.objectives[idx].copy()
            parent_record.constraint_violation = float(self.constraint_violations[idx])
            parent_record.rank = int(self.ranks[idx]) if np.isfinite(self.ranks[idx]) else 0
            parent_record.crowding_distance = float(self.crowding[idx])
            parent_record.source_sim_id = int(self.source_sim_ids[idx]) if idx < len(self.source_sim_ids) else None
            parent_record.valid = bool(self.valid_individuals[idx])
            parent_records.append(parent_record)

        combined_population = np.vstack([self.population, offspring_params])
        combined_objectives = np.vstack([self.objectives, offspring_objectives])
        combined_cv = np.concatenate([self.constraint_violations, offspring_cv])
        combined_source_sim_ids = np.concatenate([self.source_sim_ids, offspring_source_sim_ids])
        combined_records = parent_records + offspring_records

        prev_front = {
            (
                tuple(np.round(np.asarray(item["params"], dtype=float), 8)),
                tuple(np.round(np.asarray(item["objectives"], dtype=float), 8)),
            )
            for item in self.pareto_front
        }

        self._select_next_generation(
            combined_population,
            combined_objectives,
            combined_cv,
            combined_source_sim_ids,
            combined_records,
        )
        new_front = {
            (
                tuple(np.round(np.asarray(item["params"], dtype=float), 8)),
                tuple(np.round(np.asarray(item["objectives"], dtype=float), 8)),
            )
            for item in self.pareto_front
        }
        self.last_front_updated = new_front != prev_front
        self.offspring_population = self._make_offspring()

    def get_best(self) -> np.ndarray:
        if self.best_params is not None:
            return self.best_params.copy()
        return self.population[0].copy()

    def get_pareto_front(self) -> list[dict]:
        return list(self.pareto_front)
