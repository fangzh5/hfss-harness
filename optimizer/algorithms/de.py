import numpy as np
from typing import List

from .base import OptimizationAlgorithm


class DEOptimizer(OptimizationAlgorithm):
    """Differential evolution optimizer with optional JADE-style adaptation."""

    def __init__(
        self,
        bounds: List[tuple],
        pop_size: int = 30,
        F: float = 0.7,
        CR: float = 0.7,
        strategy: str = "best1bin",
        tol: float = 0.005,
        step_size: np.ndarray = None,
        initial_population: np.ndarray = None,
        pbest_rate: float = 0.15,
        c: float = 0.1,
        archive_size: int = None,
    ):
        super().__init__(bounds, pop_size)
        self.pop_size = pop_size
        self.F = float(F)
        self.CR = float(CR)
        self.strategy = str(strategy or "best1bin").lower()
        self.tol = tol
        self.step_size = step_size
        self.n_dims = len(bounds)

        self.mu_f = float(F)
        self.mu_cr = float(CR)
        self.adaptation_rate = float(c)
        self.pbest_rate = float(np.clip(pbest_rate, 0.05, 0.5))
        self.archive_size = int(archive_size or pop_size)
        self.archive = np.zeros((0, self.n_dims), dtype=float)

        self.population = self._init_population(initial_population)
        self.mutation = np.zeros_like(self.population)
        self.trial = np.zeros_like(self.population)
        self.fitness = np.full(pop_size, float("inf"))
        self.best_idx = 0

        self.trial_population = self.population.copy()
        self.trial_f = np.full(pop_size, self.F, dtype=float)
        self.trial_cr = np.full(pop_size, self.CR, dtype=float)
        self.success_f: list[float] = []
        self.success_cr: list[float] = []

    def _init_population(self, initial_population: np.ndarray = None) -> np.ndarray:
        """Initialize the initial population within bounds."""
        if initial_population is not None:
            pop = np.asarray(initial_population, dtype=float)
            expected_shape = (self.pop_size, self.n_dims)
            if pop.shape == expected_shape:
                population = pop.copy()
                for i, (low, high) in enumerate(self.bounds):
                    population[:, i] = np.clip(population[:, i], low, high)
                return population

        population = np.zeros((self.pop_size, self.n_dims))
        for i, (low, high) in enumerate(self.bounds):
            population[:, i] = np.random.uniform(low, high, self.pop_size)
        return population

    def suggest(self) -> np.ndarray:
        """Return the current best accepted individual."""
        return self.population[self.best_idx].copy()

    def suggest_population(self) -> np.ndarray:
        """Return the batch that should be evaluated next."""
        return self.trial_population.copy()

    def update(self, fitness_results: List):
        """Update accepted individuals and explicitly build the next generation."""
        self.success_f = []
        self.success_cr = []

        for result in fitness_results:
            if not hasattr(result, "cost"):
                continue

            cost = result.cost
            idx = getattr(result, "individual_idx", None)

            if idx is None:
                if cost < self.best_cost and hasattr(result, "params"):
                    self.best_cost = cost
                    self.best_params = result.params.copy()
                continue

            if idx >= self.pop_size:
                continue

            trial = self.trial_population[idx] if idx < len(self.trial_population) else self.population[idx]
            self.select(idx, trial, cost, self.trial_f[idx], self.trial_cr[idx])

        self._update_control_parameters()
        self.evolve_generation()

    def _sample_f_cr(self) -> tuple[float, float]:
        if self._use_jade():
            f = self.mu_f + 0.1 * np.random.standard_cauchy()
            tries = 0
            while (f <= 0.0 or f > 1.0) and tries < 20:
                f = self.mu_f + 0.1 * np.random.standard_cauchy()
                tries += 1
            f = float(np.clip(f, 0.05, 1.0))

            cr = np.random.normal(self.mu_cr, 0.1)
            cr = float(np.clip(cr, 0.0, 1.0))
            return f, cr

        return self.F, self.CR

    def _use_jade(self) -> bool:
        return self.strategy in {"jade", "current-to-pbest/1/bin", "current_to_pbest_1_bin"}

    def mutate(self, idx: int, f_value: float) -> np.ndarray:
        """Generate a mutant vector."""
        if self._use_jade():
            top_k = max(2, int(np.ceil(self.pbest_rate * self.pop_size)))
            ranked = np.argsort(self.fitness)
            ranked = ranked[np.isfinite(self.fitness[ranked])]
            if ranked.size == 0:
                pbest_idx = self.best_idx
            else:
                pbest_idx = int(np.random.choice(ranked[:top_k]))

            pop_and_archive = self.population if len(self.archive) == 0 else np.vstack([self.population, self.archive])
            pop_indices = [i for i in range(self.pop_size) if i != idx]
            r1 = int(np.random.choice(pop_indices))

            merged_indices = list(range(len(pop_and_archive)))
            candidate_pool = [i for i in merged_indices if not (i == idx or i == r1)]
            r2 = int(np.random.choice(candidate_pool))

            current = self.population[idx]
            pbest = self.population[pbest_idx]
            x_r1 = self.population[r1]
            x_r2 = pop_and_archive[r2]
            mutant = current + f_value * (pbest - current) + f_value * (x_r1 - x_r2)
        elif self.strategy == "best1bin":
            best = self.population[self.best_idx]
            candidates = [i for i in range(self.pop_size) if i != idx]
            r1, r2 = np.random.choice(candidates, 2, replace=False)
            mutant = best + f_value * (self.population[r1] - self.population[r2])
        else:
            candidates = [i for i in range(self.pop_size) if i != idx]
            r1, r2, r3 = np.random.choice(candidates, 3, replace=False)
            mutant = self.population[r1] + f_value * (self.population[r2] - self.population[r3])

        for i, (low, high) in enumerate(self.bounds):
            mutant[i] = np.clip(mutant[i], low, high)
        return mutant

    def crossover(self, target: np.ndarray, mutant: np.ndarray, cr_value: float) -> np.ndarray:
        """Generate a trial vector by crossover."""
        trial = target.copy()
        j_rand = np.random.randint(self.n_dims)

        for j in range(self.n_dims):
            if j == j_rand or np.random.random() < cr_value:
                trial[j] = mutant[j]
        return trial

    def _push_archive(self, parent: np.ndarray) -> None:
        if self.archive_size <= 0:
            return

        if len(self.archive) == 0:
            self.archive = parent.reshape(1, -1).copy()
        else:
            self.archive = np.vstack([self.archive, parent.reshape(1, -1)])

        if len(self.archive) > self.archive_size:
            keep = np.random.choice(len(self.archive), self.archive_size, replace=False)
            self.archive = self.archive[keep]

    def select(self, idx: int, trial: np.ndarray, trial_cost: float, f_value: float, cr_value: float) -> bool:
        """Select the trial vector if it is better than the current parent."""
        current_cost = self.fitness[idx]
        if trial_cost <= current_cost:
            previous_parent = self.population[idx].copy()
            self.population[idx] = trial
            self.fitness[idx] = trial_cost
            if np.isfinite(current_cost):
                self._push_archive(previous_parent)
            self.success_f.append(float(f_value))
            self.success_cr.append(float(cr_value))
            if trial_cost < self.best_cost:
                self.best_idx = idx
                self.best_params = trial.copy()
                self.best_cost = trial_cost
            return True
        return False

    def _update_control_parameters(self) -> None:
        if not self._use_jade():
            return
        if not self.success_f:
            return

        success_f = np.asarray(self.success_f, dtype=float)
        success_cr = np.asarray(self.success_cr, dtype=float)

        denom = np.sum(success_f)
        if denom > 1e-12:
            lehmer_f = float(np.sum(success_f ** 2) / denom)
            self.mu_f = (1.0 - self.adaptation_rate) * self.mu_f + self.adaptation_rate * lehmer_f

        self.mu_cr = (1.0 - self.adaptation_rate) * self.mu_cr + self.adaptation_rate * float(np.mean(success_cr))
        self.mu_f = float(np.clip(self.mu_f, 0.05, 1.0))
        self.mu_cr = float(np.clip(self.mu_cr, 0.0, 1.0))

    def evolve_generation(self) -> np.ndarray:
        """Build the next trial population from the accepted parents."""
        next_population = np.zeros_like(self.population)
        next_f = np.zeros(self.pop_size, dtype=float)
        next_cr = np.zeros(self.pop_size, dtype=float)

        for i in range(self.pop_size):
            f_value, cr_value = self._sample_f_cr()
            mutant = self.mutate(i, f_value)
            trial = self.crossover(self.population[i], mutant, cr_value)
            next_population[i] = trial
            next_f[i] = f_value
            next_cr[i] = cr_value

        self.trial_population = next_population
        self.trial_f = next_f
        self.trial_cr = next_cr
        return self.trial_population.copy()

    def get_best(self) -> np.ndarray:
        """Return the current best accepted individual."""
        return self.population[self.best_idx].copy()

    def check_convergence(self) -> bool:
        """Check whether the population has converged."""
        if self.best_cost < self.tol:
            return True

        finite_fitness = self.fitness[np.isfinite(self.fitness)]
        if finite_fitness.size == 0:
            return False
        fitness_std = np.std(finite_fitness)
        return fitness_std < self.tol

    @property
    def name(self) -> str:
        return "JADE" if self._use_jade() else "DE"
