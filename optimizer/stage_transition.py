"""Start a new objective stage without retaining previous objective scores."""

import copy

import numpy as np


def restart_stage(config, param_mgr, calculator, previous, raw_cache, adapter, *, factory, cache_key):
    """Rescore raw observations and construct a fresh algorithm for this stage.

    DE/PSO retain physical positions, never their old costs. BO/Surrogate retrain
    on current scores. NSGA-II rebuilds dominance from current objective vectors.
    CMA-ES deliberately restarts its covariance at the new representative point.
    """
    rescored = {}
    for key, data in raw_cache.items():
        result = calculator.calculate(data["freqs"], data["s11"], data["s12"],
                                      extra_metrics=copy.deepcopy(data["extra_metrics"]))
        if not result.valid or not np.isfinite(result.cost):
            continue
        result.params = np.asarray(data["params"], dtype=float).copy()
        result.source_sim_id = data.get("source_sim_id")
        rescored[key] = result
    multi = bool(getattr(previous, "is_multi_objective", False))
    results = list(rescored.values())
    best = min(results, key=(lambda item: (item.constraint_violation, *item.objectives))
               if multi else (lambda item: item.cost)) if results else None
    fresh_config = copy.deepcopy(config)
    options = fresh_config.setdefault("optimization", {})
    options["initial_point"] = best.params.tolist() if best is not None else None
    options.pop("seed_point", None)
    options["seed_initial_point"] = best is not None
    fresh = factory(fresh_config, param_mgr)
    method = str(config["algorithm"]["method"]).lower()

    def score(position):
        return rescored.get(cache_key(position, param_mgr, adapter))

    if method == "de":
        fresh.population = np.asarray(previous.population, dtype=float).copy()
        if best is not None:
            fresh.population[0] = best.params
        fresh.trial_population = fresh.population.copy()
        fresh.fitness = np.array([item.cost if (item := score(point)) is not None else np.inf
                                  for point in fresh.population])
        fresh.best_idx = int(np.argmin(fresh.fitness))
    elif method == "pso":
        fresh.positions = np.asarray(previous.positions, dtype=float).copy()
        if best is not None:
            fresh.positions[0] = best.params
        fresh.personal_best_positions = fresh.positions.copy()
        fresh.personal_best_costs = np.array([item.cost if (item := score(point)) is not None else np.inf
                                              for point in fresh.positions])
        fresh.global_best_position = best.params.copy() if best is not None else None
        fresh.global_best_cost = best.cost if best is not None else np.inf
    elif method == "bo" and results:
        fresh.preload_history(np.array([item.params for item in results]),
                              np.array([item.cost for item in results]))
    elif method == "surrogate" and results:
        fresh.add_training_data(np.array([item.params for item in results]),
                                np.array([item.cost for item in results]))
        fresh.train_surrogate()
        fresh.base_opt.best_params = best.params.copy()
        fresh.base_opt.best_cost = best.cost
    elif method == "nsga2":
        if len(results) >= fresh.pop_size:
            fresh._select_next_generation(
                np.array([item.params for item in results]),
                np.array([item.objectives for item in results]),
                np.array([item.constraint_violation for item in results]),
                np.array([item.source_sim_id if item.source_sim_id is not None else -1 for item in results]),
                results)
            fresh.offspring_population = fresh.population.copy()
            best = fresh.best_result
        else:
            # Keep unevaluated positions, with objectives/ranks reset by construction.
            fresh.population = np.asarray(previous.population, dtype=float).copy()
            if best is not None:
                fresh.population[0] = best.params
            fresh.offspring_population = fresh.population.copy()
    if best is not None and method != "nsga2":
        fresh.best_params = best.params.copy()
        fresh.best_cost = float(best.cost)
    return fresh, best, len(rescored)
