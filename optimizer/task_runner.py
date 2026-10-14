"""Internal task execution helpers for optimizer runs."""

import copy
import csv
import gc
import json
import os
import sys
import time
import tempfile
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from .run_deadline import parse_deadline, budget_exhausted
    from .metrics import collect_optional_metrics as _shared_collect_optional_metrics
    from .case_executor import CaseExecutor, CaseJournal, finish_journal
    from .provenance import build_execution_manifest, valid_manifest
    from .results import TraceData, ResultBundle
    from .stage_transition import restart_stage
    from .result_records import pareto_front_for_json
    from .adapters import CSVAdapter, HFSSAdapter
    from .adapters.base import SimulatorAdapter
    from .algorithms import BOOptimizer, CMAESOptimizer, DEOptimizer, NSGA2Optimizer, PSOOptimizer, SurrogateOptimizer
    from .algorithms.bo import DuplicateCandidateExhausted
    from .config_io import load_config, save_config_snapshot
    from .core import FitnessCalculator, FitnessResult, ParameterManager
    from .output_names import (
        task_data_file_name,
        task_dashboard_state_file_name,
        task_fitness_trend_file_name,
        task_history_file_name,
        task_pareto_front_file_name,
    )
    from .path_utils import (
        resolve_task_name,
        resolve_task_output_dir,
        resolve_task_work_dir,
        resolve_run_stamp,
    )
    from .sweep import run_hfss_sweep
    from .validation import run_val_cases
    from .task_config import normalize_task_type, validate_task_config, resolve_evaluation_mode
except ImportError:  # pragma: no cover
    from run_deadline import parse_deadline, budget_exhausted
    from metrics import collect_optional_metrics as _shared_collect_optional_metrics
    from case_executor import CaseExecutor, CaseJournal, finish_journal
    from provenance import build_execution_manifest, valid_manifest
    from results import TraceData, ResultBundle
    from stage_transition import restart_stage
    from result_records import pareto_front_for_json
    from adapters import CSVAdapter, HFSSAdapter
    from adapters.base import SimulatorAdapter
    from algorithms import BOOptimizer, CMAESOptimizer, DEOptimizer, NSGA2Optimizer, PSOOptimizer, SurrogateOptimizer
    from algorithms.bo import DuplicateCandidateExhausted
    from config_io import load_config, save_config_snapshot
    from core import FitnessCalculator, FitnessResult, ParameterManager
    from output_names import (
        task_data_file_name,
        task_dashboard_state_file_name,
        task_fitness_trend_file_name,
        task_history_file_name,
        task_pareto_front_file_name,
    )
    from path_utils import (
        resolve_task_name,
        resolve_task_output_dir,
        resolve_task_work_dir,
        resolve_run_stamp,
    )
    from sweep import run_hfss_sweep
    from validation import run_val_cases
    from task_config import normalize_task_type, validate_task_config, resolve_evaluation_mode

try:
    from dashboard.state_bridge import DashboardStateWriter
except Exception:
    DashboardStateWriter = None


CONFIG_FILE = "configs/template.json"
DEFAULT_CACHE_CLEANUP_EVERY = 10
CMAES_BAD_COST = 1.0e12


def _failed_batch_result(params: np.ndarray, idx: int, reason: str, calculator) -> FitnessResult:
    objectives = getattr(calculator, "multi_objective_config", {}).get("objectives", [])
    result = FitnessResult(cost=CMAES_BAD_COST, valid=False,
                           objectives=[CMAES_BAD_COST] * len(objectives),
                           constraint_violation=CMAES_BAD_COST)
    result.params = np.asarray(params, dtype=float).copy()
    result.individual_idx = int(idx)
    result.particle_idx = int(idx)
    result.failure_reason = str(reason)
    return result


def _penalize_failed_cma_results(results):
    """A failed solve must rank worse than every valid observation in this batch."""
    if not any(not getattr(item, "valid", True) for item in results):
        return
    valid_costs = [float(item.cost) for item in results if getattr(item, "valid", True)]
    penalty = CMAES_BAD_COST
    if valid_costs and max(valid_costs) >= penalty:
        with np.errstate(over="ignore"):
            penalty = float(np.nextafter(max(valid_costs), np.inf))
        if not np.isfinite(penalty):
            raise ValueError("No finite CMA failure penalty exceeds this batch's valid costs")
    for item in results:
        if not getattr(item, "valid", True):
            item.cost = penalty


DEFAULT_FITNESS_TREND_FILENAME = "fitness_trend.png"
DEFAULT_PARETO_FRONT_FILENAME = "pareto_front.png"


def create_adapter(config: dict, opt_config: dict = None, task_name: str = None) -> SimulatorAdapter:
    """Create the simulator adapter."""
    task_type = normalize_task_type(config)
    adapter_config = dict(opt_config or {})
    if task_type != "val":
        # Read-only flags are only meaningful for validation-style runs.
        adapter_config.pop("skip_simulation", None)
        adapter_config.pop("use_original_project", None)
    adapter_config["task_type"] = task_type

    if task_type in ("opt", "sweep", "val"):
        hfss_config = dict(config.get("simulator", {}).get("hfss", {}))
        if task_type == "val":
            adapter_config["evaluation_mode"] = resolve_evaluation_mode({
                **config, "optimization": {**config.get("optimization", {}), **adapter_config}})
        return HFSSAdapter(hfss_config, adapter_config, task_name)
    if task_type == "csv":
        csv_config = config.get("simulator", {}).get("csv", {})
        return CSVAdapter(csv_config)

    raise ValueError(f"Unsupported task type: {task_type}")


def create_algorithm(config: dict, param_mgr: ParameterManager):
    """Create the optimization algorithm."""
    algo_config = config.get("algorithm", {})
    method = str(algo_config.get("method", "de")).lower()
    opt_config = config.get("optimization", {})
    seed_initial_point = _should_seed_initial_point(opt_config)
    continuous_search = _use_continuous_search(method, opt_config)

    bounds = param_mgr.get_bounds()
    step_size = param_mgr.get_step_size()
    initial_point = _resolve_initial_point(opt_config, param_mgr)

    if method == "pso":
        algorithm = PSOOptimizer(
            bounds=bounds,
            n_particles=algo_config.get("population_size", 30),
            step_size=step_size,
        )
        if seed_initial_point:
            _inject_initial_point(algorithm, initial_point, param_mgr)
        return algorithm

    if method == "de":
        population_multiplier = algo_config.get("population_multiplier")
        if population_multiplier is not None:
            pop_size = int(population_multiplier) * param_mgr.n_params
        else:
            pop_size = int(algo_config.get("population_size", 30))

        initial_population = None
        if seed_initial_point and initial_point is not None:
            initial_population = _build_seeded_de_population(
                param_mgr=param_mgr,
                pop_size=pop_size,
                initial_point=initial_point,
                continuous_search=continuous_search,
            )

        algorithm = DEOptimizer(
            bounds=bounds,
            pop_size=pop_size,
            strategy=algo_config.get("strategy", "jade"),
            F=algo_config.get("mutation", 0.55),
            CR=algo_config.get("recombination", 0.9),
            step_size=step_size,
            initial_population=initial_population,
            pbest_rate=algo_config.get("pbest_rate", 0.15),
            c=algo_config.get("adaptation_rate", algo_config.get("c", 0.1)),
            archive_size=algo_config.get("archive_size"),
        )
        if seed_initial_point:
            _inject_initial_point(algorithm, initial_point, param_mgr, continuous_search=continuous_search)
        return algorithm

    if method == "nsga2":
        population_multiplier = algo_config.get("population_multiplier")
        if population_multiplier is not None:
            pop_size = int(population_multiplier) * param_mgr.n_params
        else:
            pop_size = int(algo_config.get("population_size", 40))
        multi_objective_config = config.get("target", {}).get("multi_objective", {})

        initial_population = None
        if seed_initial_point and initial_point is not None:
            initial_population = _build_seeded_de_population(
                param_mgr=param_mgr,
                pop_size=pop_size,
                initial_point=initial_point,
                continuous_search=continuous_search,
            )

        algorithm = NSGA2Optimizer(
            bounds=bounds,
            pop_size=pop_size,
            crossover_prob=algo_config.get("crossover_prob", 0.9),
            mutation_prob=algo_config.get("mutation_prob"),
            eta_c=algo_config.get("eta_c", 15.0),
            eta_m=algo_config.get("eta_m", 20.0),
            initial_population=initial_population,
            constraint_strategy=multi_objective_config.get("constraint_strategy", "constraint_domination"),
        )
        if seed_initial_point:
            _inject_initial_point(algorithm, initial_point, param_mgr, continuous_search=continuous_search)
        return algorithm

    if method == "surrogate":
        algorithm = SurrogateOptimizer(
            bounds=bounds,
            base_algorithm=algo_config.get("base_algorithm", "de"),
            n_initial=algo_config.get("n_initial", 30),
            n_candidates=algo_config.get("n_candidates", 20),
            step_size=step_size,
        )
        if seed_initial_point:
            _inject_initial_point(algorithm, initial_point, param_mgr)
        return algorithm

    if method == "bo":
        algorithm = BOOptimizer(
            bounds=bounds,
            n_initial=algo_config.get("n_initial", max(2 * param_mgr.n_params, 4)),
            strategy=algo_config.get("strategy", "tr"),
            acquisition=algo_config.get("acquisition", "log_ei"),
            raw_samples=algo_config.get("raw_samples", 128),
            num_restarts=algo_config.get("num_restarts", 8),
            neighbor_tolerance=algo_config.get("neighbor_tolerance", param_mgr.get_step_size().tolist()),
            max_duplicate_retries=algo_config.get("max_duplicate_retries", 50),
        )
        if seed_initial_point:
            _inject_initial_point(algorithm, initial_point, param_mgr, continuous_search=continuous_search)
        return algorithm

    if method == "cmaes":
        advanced = algo_config.get("advanced") or {}
        return CMAESOptimizer(
            bounds=bounds,
            initial_point=initial_point,
            mode=algo_config.get("mode", "local"),
            sigma0=advanced.get("sigma0"),
            seed=advanced.get("seed"),
        )

    raise ValueError(f"Unsupported algorithm: {method}")


def _resolve_initial_point(opt_config: dict, param_mgr: ParameterManager):
    """Resolve an optional seed point from config."""
    raw_point = opt_config.get("initial_point")
    if raw_point is None:
        raw_point = opt_config.get("seed_point")

    if raw_point is None:
        return None

    if isinstance(raw_point, dict):
        names = param_mgr.get_param_names()
        try:
            return np.array([float(raw_point[name]) for name in names], dtype=float)
        except Exception as error:
            print(f"Invalid initial_point mapping; ignored: {error}")
            return None

    try:
        values = np.array(raw_point, dtype=float)
    except Exception as error:
        print(f"Invalid initial_point value; ignored: {error}")
        return None

    if len(values) != param_mgr.n_params:
        print(
            f"Invalid initial_point length {len(values)}; expected {param_mgr.n_params}. Ignored."
        )
        return None

    return values


def _should_seed_initial_point(opt_config: dict) -> bool:
    """Return whether the resolved initial point should be injected into the search."""
    raw_flag = opt_config.get("seed_initial_point", True)
    if isinstance(raw_flag, str):
        return raw_flag.strip().lower() not in {"0", "false", "no", "off"}
    return bool(raw_flag)


def _use_continuous_search(method: str, opt_config: dict) -> bool:
    """Return whether the optimizer should search in continuous space."""
    raw_flag = opt_config.get("continuous_search")
    if raw_flag is None:
        return str(method or "").lower() in {"de", "nsga2", "bo", "cmaes"}
    if isinstance(raw_flag, str):
        return raw_flag.strip().lower() not in {"0", "false", "no", "off"}
    return bool(raw_flag)


def _normalize_history_scalar(value) -> str:
    if value in (None, ""):
        return ""
    return str(value).strip().replace("\\", "/").lower()


def _history_compat_signature(config: dict) -> dict:
    hfss = config.get("simulator", {}).get("hfss", {})
    parameters = config.get("parameters", [])
    target = config.get("target", {})
    return {
        "task_type": normalize_task_type(config),
        "project_path": _normalize_history_scalar(hfss.get("project_path")),
        "design_name": _normalize_history_scalar(hfss.get("design_name")),
        "setup_name": _normalize_history_scalar(hfss.get("setup_name")),
        "sweep_name": _normalize_history_scalar(hfss.get("sweep_name")),
        "param_names": [str(item.get("name", "")).strip() for item in parameters],
        "param_units": [_normalize_history_scalar(item.get("unit", "")) for item in parameters],
        "target": json.dumps(target, sort_keys=True, ensure_ascii=False),
    }


def _load_manual_bo_history(config: dict, algorithm, param_mgr: ParameterManager, *,
                            manifest=None, fitness_calc=None) -> dict:
    summary = {
        "requested_sources": 0,
        "accepted_sources": 0,
        "rejected_sources": 0,
        "loaded": 0,
        "skipped_out_of_bounds": 0,
        "skipped_invalid_rows": 0,
        "raw_history": [],
        "rejections": [],
    }

    algorithm_config = config.setdefault("algorithm", {})
    algorithm_config["history_loaded"] = 0

    history_config = config.get("history", {})
    if not isinstance(history_config, dict):
        return summary
    if str(algorithm_config.get("method", "")).strip().lower() != "bo":
        return summary
    if str(history_config.get("mode", "off")).strip().lower() != "manual":
        return summary
    if not hasattr(algorithm, "preload_history"):
        return summary

    sources = history_config.get("sources") or []
    if not isinstance(sources, list) or not sources:
        return summary

    summary["requested_sources"] = len(sources)
    bounds = np.asarray(param_mgr.get_bounds(), dtype=float)
    param_names = param_mgr.get_param_names()
    deduped = {}

    for source in sources:
        source_dir = os.path.abspath(os.path.expanduser(str(source)))
        try:
            if not valid_manifest(manifest) or fitness_calc is None:
                raise ValueError("Current model/solver context is unverified")
            source_manifest = json.loads(Path(source_dir, "execution_manifest.json").read_text(encoding="utf-8"))
            if not valid_manifest(source_manifest) or source_manifest["fingerprint"] != manifest["fingerprint"]:
                raise ValueError("History model/solver context differs or is unverified")
            with Path(source_dir, "cases.jsonl").open(encoding="utf-8") as stream:
                rows = [json.loads(line) for line in stream if line.strip()]
        except (OSError, ValueError, TypeError) as exc:
            summary["rejected_sources"] += 1
            summary["rejections"].append({"source": source_dir, "reason": str(exc)})
            continue
        summary["accepted_sources"] += 1
        for row in rows:
            if not isinstance(row, dict) or row.get("record_type") != "case_finished" or row.get("status") != "completed":
                continue
            try:
                params = np.asarray(row["params"], dtype=float)
                if params.shape != (param_mgr.n_params,) or not np.all(np.isfinite(params)):
                    raise ValueError("Invalid history parameter vector")
                if np.any(params < bounds[:, 0]) or np.any(params > bounds[:, 1]):
                    summary["skipped_out_of_bounds"] += 1
                    continue
                if not param_mgr.check_constraints(params):
                    raise ValueError("History point violates current constraints")
                bundle = row["result_bundle"]
                provenance = bundle["provenance"]
                if (provenance.get("execution_fingerprint") != manifest["fingerprint"]
                        or provenance.get("source_sha256") != manifest["context"]["source_sha256"]
                        or provenance.get("solved_this_call") is not True):
                    raise ValueError("History case lacks verified solve provenance")
                expected = manifest["context"]["hfss"]
                if (provenance.get("design") != manifest["context"]["actual_design"]
                        or provenance.get("setup") != expected.get("setup_name", "Setup1")
                        or provenance.get("sweep") != expected.get("sweep_name")):
                    raise ValueError("History solve used a different design/setup/sweep")
                expressions = provenance["parameters"]
                for item, value in zip(manifest["context"]["parameters"], params):
                    number, unit = HFSSAdapter._split_numeric_unit(expressions[item["name"]])
                    if number is None or unit != item["unit"] or not np.isclose(number, value, rtol=1e-12, atol=1e-15):
                        raise ValueError("History parameters disagree with acquired results")
                for name, value in manifest["context"]["baseline_expressions"].items():
                    if expressions.get(name) != value:
                        raise ValueError("History fixed/dependent baseline changed")
                for name, value in manifest["context"]["fixed_parameters"].items():
                    if str(expressions.get(name)) != str(value):
                        raise ValueError("History fixed parameter assignment differs")
                traces = {}
                for name, data in bundle["traces"].items():
                    if data["frequency_unit"] != "GHz" or data["source"].get("variation_verified") is not True:
                        raise ValueError("History trace has unverified variation or frequency units")
                    traces[name] = TraceData(data["expression"], data["frequencies"], data["values"],
                                             data["value_unit"], data["source"])
                ResultBundle(traces, provenance)
                if traces["s11"].value_unit != "dB":
                    raise ValueError("History S11 must be in dB")
                freqs, s11 = traces["s11"].frequencies_ghz, traces["s11"].values
                s12 = traces["s12"].values if "s12" in traces else None
                if s12 is not None and traces["s12"].value_unit != "dB":
                    raise ValueError("History S12 must be in dB")
                extra = row.get("extra_metrics", {})
                json.dumps(extra, allow_nan=False)
                result = fitness_calc.calculate(freqs, s11, s12, extra_metrics=copy.deepcopy(extra))
                if not result.valid or not np.isfinite(result.cost):
                    raise ValueError("History result cannot satisfy the current data contract")
                # Exact physical points, never a rounded key or a legacy CSV cost.
                key = tuple(params.tolist())
                deduped[key] = {"params": params.copy(), "freqs": freqs.copy(), "s11": s11.copy(),
                                "s12": s12.copy() if s12 is not None else None,
                                "extra_metrics": copy.deepcopy(extra), "cost": float(result.cost),
                                "source_sim_id": row.get("source_sim_id"), "source_dir": source_dir}
            except (KeyError, TypeError, ValueError, AttributeError):
                summary["skipped_invalid_rows"] += 1

    if deduped:
        params_matrix = np.array(list(deduped.keys()), dtype=float)
        costs = np.array([deduped[key]["cost"] for key in deduped], dtype=float)
        loaded = int(algorithm.preload_history(params_matrix, costs))
        summary["loaded"] = loaded
        algorithm_config["history_loaded"] = loaded
        summary["raw_history"] = list(deduped.values())

    return summary


def _project_search_params(
    params: np.ndarray,
    param_mgr: ParameterManager,
    *,
    continuous_search: bool,
) -> np.ndarray:
    """Project one candidate into the active search domain."""
    values = np.asarray(params, dtype=float)
    if continuous_search:
        return param_mgr.clamp(values)
    return param_mgr.clamp(param_mgr.discretize(values))


def _simulation_cache_key(
    params: np.ndarray,
    param_mgr: ParameterManager,
    adapter: SimulatorAdapter,
) -> tuple[str, ...]:
    """Build a cache key using the exact parameter values sent to the simulator."""
    param_names = param_mgr.get_param_names()
    param_units = list(getattr(adapter, "config", {}).get("param_units", [""] * len(param_names)))
    param_resolutions = list(
        getattr(adapter, "config", {}).get("param_resolutions", [p.resolution for p in param_mgr.parameters])
    )
    formatter = getattr(adapter, "_format_parameter_assignment", None)
    values = np.asarray(params, dtype=float)
    quantized_values = param_mgr.quantize_manufacturing(values)
    key: list[str] = []
    for idx, name in enumerate(param_names):
        value = float(values[idx])
        unit = param_units[idx] if idx < len(param_units) else ""
        resolution = param_resolutions[idx] if idx < len(param_resolutions) else None
        if callable(formatter):
            try:
                encoded = formatter(name, value, unit=unit, resolution=resolution)
            except TypeError:
                encoded = formatter(name, value, unit=unit)
        else:
            encoded = f"{float(quantized_values[idx])}{unit}"
        key.append(str(encoded))
    return tuple(key)


def _coerce_metric_value(value, adapter: HFSSAdapter):
    """Convert a metric term to a plain float when possible."""
    if value is None:
        return None

    splitter = getattr(adapter, "_split_numeric_unit", None)
    if callable(splitter):
        try:
            numeric, _ = splitter(value)
            if numeric is not None:
                return float(numeric)
        except Exception:
            pass

    try:
        return float(value)
    except Exception:
        return None


def _build_geometry_metric_extra(
    params: np.ndarray,
    param_names: list[str],
    baseline_state: dict[str, object],
    geometry_cfg: dict,
    adapter: HFSSAdapter,
) -> dict:
    """Build a soft geometry penalty from the current parameter state."""
    if not isinstance(geometry_cfg, dict) or not geometry_cfg.get("enabled", False):
        return {}

    current_map = {str(name): float(value) for name, value in zip(param_names, np.asarray(params, dtype=float))}
    metric = 0.0
    used_terms: dict[str, float] = {}

    for term in geometry_cfg.get("terms", []):
        if not isinstance(term, dict):
            continue
        name = str(term.get("name", "")).strip()
        if not name:
            continue

        try:
            coef = float(term.get("coef", 1.0))
        except Exception:
            coef = 1.0

        source = str(term.get("source", "current")).strip().lower()
        value = None
        if source == "baseline":
            value = baseline_state.get(name)
        elif source == "current":
            value = current_map.get(name, baseline_state.get(name))
        else:
            value = current_map.get(name, baseline_state.get(name))

        numeric = _coerce_metric_value(value, adapter)
        if numeric is None:
            continue

        metric += coef * numeric
        used_terms[name] = float(numeric)

    if not used_terms:
        return {}

    return {
        "geometry_metric": float(metric),
        "geometry_metric_terms": used_terms,
    }


def _inject_initial_point(
    algorithm,
    initial_point,
    param_mgr: ParameterManager,
    *,
    continuous_search: bool = False,
):
    """Place a seed point into the first member of the initial population."""
    if initial_point is None:
        return

    seed = _project_search_params(
        np.array(initial_point, dtype=float),
        param_mgr,
        continuous_search=continuous_search,
    )
    try:
        algorithm.seed_point = seed.copy()
    except Exception:
        pass

    injected = False

    if hasattr(algorithm, "population") and len(getattr(algorithm, "population", [])) > 0:
        algorithm.population[0] = seed.copy()
        injected = True
        if hasattr(algorithm, "fitness") and len(getattr(algorithm, "fitness", [])) > 0:
            algorithm.fitness[0] = float("inf")
        if hasattr(algorithm, "trial_population") and len(getattr(algorithm, "trial_population", [])) > 0:
            algorithm.trial_population[0] = seed.copy()
        if hasattr(algorithm, "offspring_population") and len(getattr(algorithm, "offspring_population", [])) > 0:
            algorithm.offspring_population[0] = seed.copy()

    if hasattr(algorithm, "positions") and len(getattr(algorithm, "positions", [])) > 0:
        algorithm.positions[0] = seed.copy()
        injected = True
        if hasattr(algorithm, "personal_best_positions") and len(getattr(algorithm, "personal_best_positions", [])) > 0:
            algorithm.personal_best_positions[0] = seed.copy()
        if hasattr(algorithm, "velocities") and len(getattr(algorithm, "velocities", [])) > 0:
            algorithm.velocities[0] = 0.0

    if hasattr(algorithm, "base_opt"):
        _inject_initial_point(
            algorithm.base_opt,
            seed,
            param_mgr,
            continuous_search=continuous_search,
        )

    if injected:
        print(f"Seed point injected into initial population: {seed.tolist()}")


def _build_seeded_de_population(
    param_mgr: ParameterManager,
    pop_size: int,
    initial_point,
    *,
    continuous_search: bool = False,
) -> np.ndarray:
    """Build a DE initial population with one seed and global coverage.

    The seed occupies the first individual. All remaining individuals are sampled
    across the full parameter bounds using a Latin-hypercube-style layout so JADE
    keeps its global exploration behavior instead of collapsing into a tight local
    cloud around the initial point.
    """
    seed = _project_search_params(
        np.array(initial_point, dtype=float),
        param_mgr,
        continuous_search=continuous_search,
    )
    bounds = np.array(param_mgr.get_bounds(), dtype=float)

    population = np.zeros((pop_size, param_mgr.n_params), dtype=float)
    population[0] = seed.copy()

    if pop_size <= 1:
        return population

    remaining = pop_size - 1
    lhs = np.zeros((remaining, param_mgr.n_params), dtype=float)
    for dim, (low, high) in enumerate(bounds):
        cut_points = np.linspace(0.0, 1.0, remaining + 1)
        samples = cut_points[:-1] + np.random.uniform(0.0, 1.0 / remaining, remaining)
        np.random.shuffle(samples)
        lhs[:, dim] = low + samples * (high - low)

    for i in range(remaining):
        candidate = _project_search_params(
            lhs[i],
            param_mgr,
            continuous_search=continuous_search,
        )
        population[i + 1] = candidate

    return population


def _revalidate_export_candidate(
    config: dict,
    adapter: SimulatorAdapter,
    param_mgr: ParameterManager,
    fitness_calc: FitnessCalculator,
    best_params: np.ndarray | None,
    *, executor=None, case_id=None, enrich_metrics=None,
    case_role="export_verification", case_fields=None, before_solve=None,
):
    """Quantize the best point for manufacturing and re-evaluate it."""
    if best_params is None:
        return None, None, None

    export_params = param_mgr.quantize_manufacturing(np.asarray(best_params, dtype=float))
    export_params = param_mgr.repair_constraints(export_params)
    if not param_mgr.check_constraints(export_params):
        raise RuntimeError("Manufacturable export parameters violate constraints")

    if executor is not None:
        outcome = executor.execute(
            case_id, dict(zip(param_mgr.get_param_names(), export_params.tolist())),
            parameter_vector=export_params, retain_success_state=True,
            fields={**(case_fields or {}), "case_role": case_role, "params": export_params.tolist()},
            before_solve=before_solve,
            enrich_metrics=(lambda extra: enrich_metrics(extra, export_params)) if enrich_metrics else None)
        if outcome.status != "completed":
            raise RuntimeError(f"Manufacturable export verification failed: {outcome.failure_reason}")
        outcome.fitness.params = export_params.copy()
        return export_params, float(outcome.fitness.cost), outcome.fitness

    if not adapter.set_parameters(export_params):
        raise RuntimeError("Failed to apply manufacturable export parameters")

    freqs, s11, s12 = adapter.simulate()
    if freqs is None or s11 is None:
        raise RuntimeError("Failed to solve manufacturable export parameters")

    try:
        extra_metrics = _collect_optional_metrics(config, adapter)
        export_result = fitness_calc.calculate(freqs, s11, s12, extra_metrics=extra_metrics)
        if not getattr(export_result, "valid", True):
            raise RuntimeError(export_result.failure_reason or "Invalid export result")
        export_result.params = export_params.copy()
        export_cost = float(getattr(export_result, "cost", float("inf")))
    except Exception as exc:
        raise RuntimeError(f"Manufacturable export verification failed: {exc}") from exc

    print(f"Manufacturable export point revalidated: {export_params.tolist()} | cost={export_cost:.4f}")
    return export_params, export_cost, export_result


def _describe_target(target_config: dict) -> str:
    """Format the active target or staged targets for console output."""
    stages = target_config.get("stages") or []
    if not stages:
        freq_band = target_config.get("freq_band")
        threshold = target_config.get("s11_threshold")
        s12_threshold = target_config.get("s12_threshold", target_config.get("s21_threshold"))
        lower_bands = target_config.get("s11_lower_bands") or []
        lower_text = ""
        if lower_bands:
            parts = []
            for band in lower_bands:
                if not isinstance(band, dict):
                    continue
                band_range = band.get("freq_band")
                lower_threshold = band.get("threshold")
                comparator = ">" if band.get("strict", False) else ">="
                parts.append(f"S11{comparator}{lower_threshold} dB @ {band_range} GHz")
            if parts:
                lower_text = " | " + ", ".join(parts)
        if s12_threshold is None:
            return f"S11<={threshold} dB @ {freq_band} GHz{lower_text}"
        return f"S11<={threshold} dB, S12<={s12_threshold} dB @ {freq_band} GHz{lower_text}"

    parts = []
    for idx, stage in enumerate(stages, start=1):
        name = stage.get("name", f"stage_{idx}")
        band = stage.get("freq_band", target_config.get("freq_band"))
        threshold = stage.get("s11_threshold", target_config.get("s11_threshold"))
        s12_threshold = stage.get("s12_threshold", stage.get("s21_threshold", target_config.get("s12_threshold", target_config.get("s21_threshold"))))
        bw = stage.get("bandwidth_target", target_config.get("bandwidth_target"))
        if s12_threshold is None:
            parts.append(f"{name}: {band} GHz, S11<={threshold} dB, bw>={bw}")
        else:
            parts.append(f"{name}: {band} GHz, S11<={threshold} dB, S12<={s12_threshold} dB, bw>={bw}")
    return " -> ".join(parts)


def _get_candidate_batch(algorithm):
    """Return a candidate batch and whether the algorithm is batch-based."""
    if hasattr(algorithm, "suggest_population"):
        candidates = np.asarray(algorithm.suggest_population(), dtype=float)
        if candidates.ndim != 2 or candidates.shape[0] == 0 or not np.all(np.isfinite(candidates)):
            raise ValueError("Algorithm must ask a nonempty finite 2D candidate batch")
        return candidates, True
    return np.array([algorithm.suggest()]), False


def _sync_candidate_state(algorithm, idx: int, params: np.ndarray):
    """Keep algorithm state aligned with evaluated candidates."""
    if hasattr(algorithm, "trial_population") and idx < len(getattr(algorithm, "trial_population", [])):
        try:
            algorithm.trial_population[idx] = params.copy()
        except Exception:
            pass

    if hasattr(algorithm, "offspring_population") and idx < len(getattr(algorithm, "offspring_population", [])):
        try:
            algorithm.offspring_population[idx] = params.copy()
        except Exception:
            pass

    if hasattr(algorithm, "positions") and idx < len(getattr(algorithm, "positions", [])):
        try:
            algorithm.positions[idx] = params.copy()
        except Exception:
            pass

    if (
        hasattr(algorithm, "population")
        and not hasattr(algorithm, "offspring_population")
        and not hasattr(algorithm, "trial_population")
        and idx < len(getattr(algorithm, "population", []))
    ):
        try:
            algorithm.population[idx] = params.copy()
        except Exception:
            pass


def _is_transient_cleanup_error(error: Exception) -> bool:
    """Return True when the cleanup failure looks like a temporary lock conflict."""
    winerror = getattr(error, "winerror", None)
    if winerror == 32:
        return True

    message = str(error).lower()
    return (
        "winerror 32" in message
        or "semaphore" in message
        or "in use" in message
        or "正在使用此文件" in message
        or "进程无法访问" in message
    )


def _cleanup_aedt_cache(adapter: SimulatorAdapter, attempts: int = 3, initial_wait: float = 1.0, retry_wait: float = 2.0):
    """Remove solved data through AEDT, keep exported files untouched.

    The cleanup is intentionally conservative:
    - flush the project first,
    - give AEDT a moment to release solver handles,
    - retry a few times if the cache is still locked.
    """
    app = getattr(adapter, "app", None)
    if app is None or not hasattr(app, "cleanup_solution"):
        print("Cache cleanup failed: cleanup API not available")
        return

    total_attempts = max(1, attempts)

    try:
        gc.collect()
    except Exception:
        pass

    time.sleep(max(0.0, initial_wait))

    try:
        app.save_project()
    except Exception as save_error:
        print(f"Cleanup pre-save failed: {save_error}")

    last_error = None
    for attempt in range(1, total_attempts + 1):
        try:
            ok = app.cleanup_solution(
                variations="All",
                entire_solution=True,
                field=True,
                mesh=True,
                linked_data=True,
            )
            if ok:
                try:
                    app.save_project()
                except Exception as save_error:
                    print(f"Cleanup save failed: {save_error}")
                print(f"Solution cache cleaned (attempt {attempt}/{total_attempts})")
                return

            last_error = RuntimeError("cleanup_solution returned false")
            print(f"Cleanup attempt {attempt}/{total_attempts} returned false")
        except Exception as error:
            last_error = error
            print(f"Cleanup attempt {attempt}/{total_attempts} failed: {error}")

            if not _is_transient_cleanup_error(error):
                print("Cleanup failure does not look transient; retrying conservatively")

        if attempt < attempts:
            try:
                time.sleep(max(0.0, retry_wait))
            except Exception:
                pass
            try:
                gc.collect()
            except Exception:
                pass

    print(f"Cache cleanup failed after {total_attempts} attempts: {last_error}")


def _target_requires_far_field_metrics(config: dict) -> bool:
    """Return True when the target objectives cannot be evaluated without far-field data."""
    target = config.get("target", {})
    if target.get("gain_min") is not None:
        return True
    far_field_cfg = target.get("far_field") or target.get("boresight")
    if isinstance(far_field_cfg, dict) and bool(far_field_cfg.get("required", False)):
        return True

    multi_objective = target.get("multi_objective", {})
    if not isinstance(multi_objective, dict) or not bool(multi_objective.get("enabled", False)):
        return False

    for objective in multi_objective.get("objectives", []):
        if not isinstance(objective, dict):
            continue
        obj_type = str(objective.get("type", objective.get("name", ""))).strip().lower()
        if (
            obj_type.startswith("peak_gain")
            or obj_type.startswith("pointing_error")
            or obj_type.startswith("peak_loss")
            or obj_type.startswith("boresight_gain")
        ):
            return True
    return False


def _print_simulation_header(
    sim_id: int,
    iteration: int,
    setup_name: str,
    params: np.ndarray,
    param_names: list,
    cleanup_every: int,
):
    """Print a compact separator before each simulation."""
    print(flush=True)
    print("=" * 58, flush=True)
    print(f"[sim_id={sim_id} | iter={iteration} | setup={setup_name} | cleanup={cleanup_every}]", flush=True)
    if param_names:
        pairs = ", ".join(f"{name}={value:.4f}" for name, value in zip(param_names, params))
        print(f"Params: {pairs}", flush=True)
    else:
        print(f"Params: {params.tolist()}", flush=True)
    print("Status: starting simulation", flush=True)
    print("=" * 58, flush=True)


def _collect_optional_metrics(config: dict, adapter: SimulatorAdapter) -> dict:
    """Compatibility entry point for the shared, trace-aware metric collector."""
    return _shared_collect_optional_metrics(config, adapter)


def _save_pareto_front(task_output_dir: str, algorithm, param_names: list[str], task_type: str = "opt") -> str | None:
    """Persist the current Pareto front if the algorithm exposes one."""
    if not getattr(algorithm, "is_multi_objective", False):
        return None
    if not hasattr(algorithm, "get_pareto_front"):
        return None

    pareto_front = pareto_front_for_json(algorithm.get_pareto_front())
    if not pareto_front:
        return None

    output_path = os.path.join(task_output_dir, task_pareto_front_file_name(task_type, "json"))
    payload = []
    for item in pareto_front:
        params = item.get("params", [])
        payload.append(
            {
                **item,
                "params_map": {
                    name: float(value)
                    for name, value in zip(param_names, params)
                },
            }
        )

    serialized = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
    with open(output_path, "w", encoding="utf-8") as fp:
        fp.write(serialized)

    print(f"Pareto front saved: {output_path}")
    return output_path


def _sync_adapter_best_state(adapter: SimulatorAdapter, best_params: np.ndarray | None, best_cost: float | None) -> None:
    """Ensure the adapter can restore the representative best candidate before saving."""
    if best_params is None:
        adapter.best_params = None
        adapter.best_fitness = float("inf")
        return

    try:
        adapter.best_params = np.asarray(best_params, dtype=float).copy()
    except Exception:
        pass

    try:
        if best_cost is not None:
            adapter.best_fitness = float(best_cost)
    except Exception:
        pass


def plot_s11(freqs: np.ndarray, s11: np.ndarray, output_path: str = None, threshold: float = -10):
    """Plot S11 versus frequency."""
    f_ghz = np.asarray(freqs, dtype=float)

    plt.figure(figsize=(10, 6))
    plt.plot(f_ghz, s11, "b-", linewidth=2)
    plt.axhline(threshold, color="r", linestyle="--", alpha=0.7, label=f"{threshold:.0f} dB")
    plt.xlabel("Frequency (GHz)")
    plt.ylabel("S11 (dB)")
    plt.title("S11 vs Frequency")
    plt.grid(True, alpha=0.3)
    plt.legend()

    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        print(f"Saved plot: {output_path}")
    else:
        plt.show()


def plot_fitness_trend(raw_costs: list[float], output_path: str = None):
    """Plot raw fitness and best-so-far fitness versus simulation count."""
    if not raw_costs:
        return

    raw = np.asarray(raw_costs, dtype=float)
    sims = np.arange(1, raw.size + 1)
    best = np.minimum.accumulate(raw)

    fig, ax = plt.subplots(figsize=(10.5, 5.8))
    ax.plot(sims, raw, color="#999999", linewidth=1.0, alpha=0.55, label="raw fitness")
    ax.plot(sims, best, color="#1f77b4", linewidth=2.4, label="best-so-far")
    ax.scatter([sims[0], sims[-1]], [best[0], best[-1]], color=["#2ca02c", "#d62728"], s=28, zorder=3)
    ax.set_title("Raw Fitness vs Best-so-far")
    ax.set_xlabel("Simulation #")
    ax.set_ylabel("Fitness (cost)")
    ax.grid(True, alpha=0.25)
    ax.legend(frameon=False)
    fig.tight_layout()

    if output_path:
        output_path = str(output_path)
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        tmp_fd, tmp_name = tempfile.mkstemp(prefix="fitness_trend_", suffix=".png", dir=output_dir or None)
        try:
            os.close(tmp_fd)
            fig.savefig(tmp_name, dpi=160, bbox_inches="tight")
            os.replace(tmp_name, output_path)
        finally:
            if os.path.exists(tmp_name):
                try:
                    os.remove(tmp_name)
                except OSError:
                    pass
    else:
        plt.show()

    plt.close(fig)


def plot_pareto_front(
    pareto_front: list[dict],
    output_path: str = None,
    objective_defs: list[dict] | None = None,
):
    """Plot the current Pareto front for multi-objective runs."""
    if not pareto_front:
        return

    xs = []
    ys = []
    for item in pareto_front:
        objectives = item.get("objectives", [])
        if len(objectives) < 2:
            continue
        xs.append(float(objectives[0]))
        ys.append(float(objectives[1]))

    if not xs:
        return

    x_label = "objective_1"
    y_label = "objective_2"
    if objective_defs and len(objective_defs) >= 2:
        x_label = str(objective_defs[0].get("name", objective_defs[0].get("type", x_label)))
        y_label = str(objective_defs[1].get("name", objective_defs[1].get("type", y_label)))

    fig, ax = plt.subplots(figsize=(8.5, 6.2))
    ax.scatter(xs, ys, color="#1f77b4", s=42, alpha=0.9)
    ax.set_title("Pareto Front")
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.grid(True, alpha=0.25)
    fig.tight_layout()

    if output_path:
        output_path = str(output_path)
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        tmp_fd, tmp_name = tempfile.mkstemp(prefix="pareto_front_", suffix=".png", dir=output_dir or None)
        try:
            os.close(tmp_fd)
            fig.savefig(tmp_name, dpi=160, bbox_inches="tight")
            os.replace(tmp_name, output_path)
        finally:
            if os.path.exists(tmp_name):
                try:
                    os.remove(tmp_name)
                except OSError:
                    pass
    else:
        plt.show()

    plt.close(fig)


class OptimizationLogger:
    """Simple CSV logger for the optimization loop."""

    def __init__(self, log_path: str, param_names: list):
        self.log_path = log_path
        self.param_names = param_names
        self.sim_id = 0
        self.fp = open(log_path, "w", encoding="utf-8")

        self.component_columns = [
            "violation_cost",
            "bandwidth_cost",
            "coverage_cost",
            "depth_bonus",
            "geometry_penalty",
            "s12_cost",
            "gain_cost",
            "constraint_penalty",
        ]
        self.raw_metric_columns = [
            "violation_raw",
            "bandwidth_gap_raw",
            "coverage_gap_raw",
            "depth_raw",
            "s12_violation_raw",
            "gain_violation_raw",
            "geometry_raw",
            "constraint_raw",
        ]
        self.adaptive_columns = [
            "adaptive_violation",
            "adaptive_bandwidth",
            "adaptive_coverage",
            "adaptive_s12",
            "adaptive_gain",
        ]
        self.objective_columns = [
            "constraint_violation",
            "objective_1",
            "objective_2",
            "objective_3",
        ]
        self.bo_columns = [
            "bo_phase",
            "bo_pred_mean",
            "bo_pred_std",
            "bo_abs_error",
        ]

        header = "sim_id,iter,cost,s11_max,bandwidth,s12_max,target_met,checkpoint"
        header += "," + ",".join(self.component_columns)
        header += "," + ",".join(self.raw_metric_columns)
        header += "," + ",".join(self.adaptive_columns)
        header += "," + ",".join(self.objective_columns)
        header += "," + ",".join(self.bo_columns)
        if param_names:
            header += "," + ",".join(param_names)
        self.fp.write(header + "\n")
        self.fp.flush()

    def log(
        self,
        iteration: int,
        cost: float,
        s11_max: float = None,
        bandwidth: float = None,
        s12_max: float = None,
        target_met: bool = False,
        params: np.ndarray = None,
        is_checkpoint: bool = False,
        component_costs: dict = None,
        raw_metrics: dict = None,
        adaptive_scales: dict = None,
        objectives: list = None,
        constraint_violation: float = None,
        bo_diagnostics: dict = None,
    ):
        component_costs = component_costs or {}
        raw_metrics = raw_metrics or {}
        adaptive_scales = adaptive_scales or {}
        objectives = objectives or []
        bo_diagnostics = bo_diagnostics or {}
        self.sim_id += 1
        parts = [
            str(self.sim_id),
            str(iteration),
            f"{cost:.6f}",
            f"{s11_max:.2f}" if s11_max is not None else "N/A",
            f"{bandwidth:.4f}" if bandwidth is not None else "N/A",
            f"{s12_max:.2f}" if s12_max is not None else "N/A",
            str(target_met),
            str(is_checkpoint),
        ]
        for key in self.component_columns:
            value = component_costs.get(key)
            parts.append(f"{float(value):.6f}" if value is not None else "0.000000")
        for key in self.raw_metric_columns:
            value = raw_metrics.get(key)
            parts.append(f"{float(value):.6f}" if value is not None else "0.000000")
        adaptive_map = {
            "adaptive_violation": adaptive_scales.get("violation"),
            "adaptive_bandwidth": adaptive_scales.get("bandwidth"),
            "adaptive_coverage": adaptive_scales.get("coverage"),
            "adaptive_s12": adaptive_scales.get("s12"),
            "adaptive_gain": adaptive_scales.get("gain"),
        }
        for key in self.adaptive_columns:
            value = adaptive_map.get(key)
            parts.append(f"{float(value):.6f}" if value is not None else "1.000000")
        objective_values = [constraint_violation] + list(objectives[:3])
        while len(objective_values) < len(self.objective_columns):
            objective_values.append(None)
        for value in objective_values[: len(self.objective_columns)]:
            parts.append(f"{float(value):.6f}" if value is not None else "N/A")
        parts.append(str(bo_diagnostics.get("phase", "") or ""))
        for key in ("pred_mean", "pred_std", "abs_error"):
            value = bo_diagnostics.get(key)
            parts.append(f"{float(value):.6f}" if value is not None else "N/A")
        if params is not None:
            parts.extend([f"{p:.6f}" for p in params])

        self.fp.write(",".join(parts) + "\n")
        self.fp.flush()

    def close(self):
        if self.fp:
            self.fp.close()


class SimulationDataLogger:
    """Store full simulation traces."""

    def __init__(
        self,
        output_dir: str,
        param_names: list,
        task_type: str,
        enabled: bool = True,
        storage_format: str = "jsonl",
    ):
        self.output_dir = output_dir
        self.param_names = param_names
        self.task_type = normalize_task_type({"task_type": task_type})
        self.sim_id = 0
        self.enabled = enabled
        self.storage_format = (storage_format or "jsonl").lower()
        self._far_field_meta_written = False

        if not self.enabled:
            self.full_path = None
            self.full_fp = None
            return

        os.makedirs(output_dir, exist_ok=True)

        if self.storage_format == "csv":
            self.full_path = os.path.join(output_dir, task_data_file_name(self.task_type, "csv"))
            self.full_fp = open(self.full_path, "w", encoding="utf-8", newline="")
            header = ["sim_id", "iter"]
            if param_names:
                header.extend(param_names)
            header.extend(["s_freqs", "s11", "s12", "g_freqs", "gain"])
            self.full_fp.write(",".join(header) + "\n")
        else:
            self.full_path = os.path.join(output_dir, task_data_file_name(self.task_type, "jsonl"))
            self.full_fp = open(self.full_path, "w", encoding="utf-8")

        self.full_fp.flush()

    @staticmethod
    def _to_float_list(values):
        return [float(value) for value in (values or [])]

    def _build_far_field_meta_record(self, far_field: dict):
        if not isinstance(far_field, dict):
            return None

        per_frequency = far_field.get("per_frequency")
        if not isinstance(per_frequency, list) or not per_frequency:
            return None

        plane_meta = {}
        for plane_id in ("primary_plane", "orthogonal_plane"):
            plane_info = None
            for item in per_frequency:
                plane_cuts = item.get("plane_cuts") if isinstance(item, dict) else None
                if not isinstance(plane_cuts, dict):
                    continue
                candidate = plane_cuts.get(plane_id)
                if isinstance(candidate, dict) and candidate.get("cut_angle_deg"):
                    plane_info = candidate
                    break
            if not plane_info:
                continue
            plane_meta[plane_id] = {
                "plane_phi_deg": float(plane_info.get("plane_phi_deg", 0.0)),
                "plane_include_opposite": bool(plane_info.get("plane_include_opposite", True)),
                "cut_angle_deg": self._to_float_list(plane_info.get("cut_angle_deg", [])),
            }

        return {
            "record_type": "far_field_meta",
            "schema_version": 1,
            "far_field": {
                "freqs_ghz": [
                    float(str(freq).replace("GHz", "").strip())
                    for freq in far_field.get("frequencies", [])
                ],
                "planes": plane_meta,
            },
        }

    def _build_far_field_simulation_record(self, far_field: dict):
        if not isinstance(far_field, dict):
            return None

        per_frequency = far_field.get("per_frequency")
        if not isinstance(per_frequency, list) or not per_frequency:
            return None

        cuts = {"primary_plane": [], "orthogonal_plane": []}
        global_peak = {"theta_deg": [], "phi_deg": [], "gain_db": []}
        any_cut = False
        any_peak = False

        for item in per_frequency:
            if not isinstance(item, dict):
                continue

            peak_info = item.get("global_peak_direction")
            if isinstance(peak_info, dict):
                global_peak["theta_deg"].append(float(peak_info.get("theta_deg", 0.0)))
                global_peak["phi_deg"].append(float(peak_info.get("phi_deg", 0.0)))
                global_peak["gain_db"].append(float(peak_info.get("gain_db", 0.0)))
                any_peak = True

            plane_cuts = item.get("plane_cuts")
            if not isinstance(plane_cuts, dict):
                continue

            for plane_id in cuts:
                cut_info = plane_cuts.get(plane_id)
                if isinstance(cut_info, dict):
                    cuts[plane_id].append(self._to_float_list(cut_info.get("gain_db", [])))
                    any_cut = True
                elif cuts[plane_id]:
                    cuts[plane_id].append([])

        payload = {}
        if any_cut:
            payload["cuts"] = {plane_id: {"gain_db": values} for plane_id, values in cuts.items() if values}
        if any_peak:
            payload["global_peak"] = global_peak
        return payload or None

    def log_simulation(
        self,
        iter_num: int,
        params: np.ndarray,
        freqs: np.ndarray,
        s11: np.ndarray,
        s12: np.ndarray,
        g_freqs: np.ndarray = None,
        gain: np.ndarray = None,
        extra_metrics: dict = None,
    ):
        if not self.enabled or not self.full_fp:
            return

        self.sim_id += 1

        if self.storage_format == "csv":
            parts = [str(self.sim_id), str(iter_num)]
            if params is not None:
                parts.extend([f"{p:.6f}" for p in params])

            s_freqs_json = json.dumps(freqs.tolist()) if freqs is not None else "[]"
            s11_json = json.dumps(s11.tolist()) if s11 is not None else "[]"
            s12_json = json.dumps(s12.tolist()) if s12 is not None else ""
            g_freqs_json = json.dumps(g_freqs.tolist()) if g_freqs is not None else ""
            gain_json = json.dumps(gain.tolist()) if gain is not None else ""

            parts.extend([s_freqs_json, s11_json, s12_json, g_freqs_json, gain_json])
            self.full_fp.write(",".join(parts) + "\n")
        else:
            far_field = extra_metrics.get("far_field") if isinstance(extra_metrics, dict) else None
            if not self._far_field_meta_written and isinstance(far_field, dict):
                meta_record = self._build_far_field_meta_record(far_field)
                if meta_record is not None:
                    self.full_fp.write(json.dumps(meta_record, ensure_ascii=False) + "\n")
                    self._far_field_meta_written = True
            record = {
                "sim_id": self.sim_id,
                "iter": iter_num,
                "params": {name: float(value) for name, value in zip(self.param_names, params)} if params is not None else {},
                "s_freqs": freqs.tolist() if freqs is not None else [],
                "s11": s11.tolist() if s11 is not None else [],
                "s12": s12.tolist() if s12 is not None else [],
                "g_freqs": g_freqs.tolist() if g_freqs is not None else [],
                "gain": gain.tolist() if gain is not None else [],
            }
            far_field_record = self._build_far_field_simulation_record(far_field)
            if far_field_record is not None:
                record["far_field"] = far_field_record
            bo_diagnostics = extra_metrics.get("bo_diagnostics") if isinstance(extra_metrics, dict) else None
            if isinstance(bo_diagnostics, dict):
                record["bo_diagnostics"] = bo_diagnostics
            for key in ("result_bundle", "traces"):
                if isinstance(extra_metrics, dict) and key in extra_metrics:
                    record[key] = extra_metrics[key]
            self.full_fp.write(json.dumps(record, ensure_ascii=False) + "\n")

        self.full_fp.flush()

    def close(self):
        if self.full_fp:
            self.full_fp.close()


def run_optimization(config: dict, adapter: HFSSAdapter, param_mgr: ParameterManager,
                     fitness_calc: FitnessCalculator, algorithm):
    """Keep compatibility returns while recording failures and closing every log."""
    opt = config.get("optimization", {})
    output_dir = Path(opt.get("task_output_dir") or resolve_task_output_dir(config, run_stamp=opt.get("run_stamp")))
    journal = CaseJournal(output_dir / "cases.jsonl")
    resources = []
    adapter.last_task_outcome = {"status": "Running"}
    adapter._task_dashboard_writer = None
    adapter._task_completion_message = None
    adapter._case_executor = None
    adapter._optimization_finished = False
    adapter._optimization_export_saved = False
    try:
        result = _run_optimization_impl(config, adapter, param_mgr, fitness_calc, algorithm, journal, resources)
        # Search cases already restore themselves. Final export deliberately
        # retains its verified point; nothing should mutate the work model now.
        (output_dir / "optimization_summary.json").write_text(
            json.dumps(adapter.last_task_outcome, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        finish_journal(journal, status=adapter.last_task_outcome["status"],
                       reason=adapter._task_completion_message or adapter.last_task_outcome.get("termination_reason"),
                       writer=adapter._task_dashboard_writer)
        return result
    except BaseException as exc:
        status = "Stopped" if isinstance(exc, KeyboardInterrupt) else "Failed"
        restore_error = None
        if adapter._case_executor is not None and not adapter._optimization_export_saved:
            try:
                adapter._case_executor.restore()
            except Exception as error:
                restore_error = str(error)
                status = "Failed"
        adapter.last_task_outcome = {**adapter.last_task_outcome, "status": status,
                                    "failure_reason": str(exc) or type(exc).__name__}
        if restore_error is not None:
            adapter.last_task_outcome["restore_failure"] = restore_error
        finish_journal(journal, status=status, reason=adapter.last_task_outcome["failure_reason"],
                       writer=adapter._task_dashboard_writer)
        (output_dir / "optimization_summary.json").write_text(
            json.dumps(adapter.last_task_outcome, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        raise
    finally:
        adapter._optimization_finished = True
        for resource in resources:
            resource.close()
        journal.close()


def _run_optimization_impl(config: dict, adapter: HFSSAdapter, param_mgr: ParameterManager,
                           fitness_calc: FitnessCalculator, algorithm, journal, resources):
    """Run the optimization loop."""
    task_type = normalize_task_type(config)
    target_config = config.get("target", {})
    algo_config = config.get("algorithm", {})
    output_config = config.get("output", {})
    opt_config = config.get("optimization", {})
    algo_method = str(algo_config.get("method", "de")).lower()
    stop_on_target = opt_config.get("stop_on_target", not fitness_calc.is_multi_objective)
    continuous_search = _use_continuous_search(algo_method, opt_config)
    task_name = config.get("name", "task")
    hfss_config = config.get("simulator", {}).get("hfss", {})
    setup_name = hfss_config.get("setup_name", "Setup1")

    max_iters = algo_config.get("max_iterations", 50)
    raw_patience = algo_config.get("early_stop_patience", 15)
    try:
        patience = int(raw_patience)
    except Exception:
        patience = 15
    early_stop_enabled = patience > 0
    max_simulations = algo_config.get("max_simulations")
    max_attempts = opt_config.get("max_attempts", max(50, int(max_iters) * int(algo_config.get("population_size", 30)) * 5))
    max_failures = opt_config.get("max_consecutive_failures", 5)
    for name, value in (("max_attempts", max_attempts), ("max_consecutive_failures", max_failures)):
        if type(value) is not int or value < 1:
            raise ValueError(f"optimization.{name} must be a positive integer")
    end_at = parse_deadline(opt_config.get("end_at"))
    longest_simulation = 0.0
    save_interval = opt_config.get("save_interval", 10)
    if type(save_interval) is not int or save_interval < 0:
        raise ValueError("optimization.save_interval must be a nonnegative integer")
    cleanup_every = opt_config.get("cleanup_every", DEFAULT_CACHE_CLEANUP_EVERY)
    try:
        cleanup_every = int(cleanup_every)
    except Exception:
        cleanup_every = DEFAULT_CACHE_CLEANUP_EVERY
    if cleanup_every <= 0:
        cleanup_every = DEFAULT_CACHE_CLEANUP_EVERY
    run_stamp = opt_config.get("run_stamp")
    initial_point = _resolve_initial_point(opt_config, param_mgr)
    seed_initial_point = _should_seed_initial_point(opt_config)
    seed_point = None
    if seed_initial_point and initial_point is not None:
        seed_point = _project_search_params(
            np.array(initial_point, dtype=float),
            param_mgr,
            continuous_search=continuous_search,
        )

    geometry_metric_config = target_config.get("fitness", {}).get("geometry_metric", {})
    geometry_baseline_state: dict[str, object] = {}
    if isinstance(geometry_metric_config, dict) and geometry_metric_config.get("enabled", False):
        try:
            geometry_baseline_state = adapter.capture_current_parameter_state(param_mgr.get_param_names())
            print("Geometry metric baseline captured.")
        except Exception as exc:
            print(f"Geometry metric baseline capture failed: {exc}")
            geometry_baseline_state = {}
    if initial_point is not None and not seed_initial_point:
        print("Initial point captured for reference only; not injected into the population.")

    task_output_dir = opt_config.get("task_output_dir") or resolve_task_output_dir(config, run_stamp=run_stamp)
    task_output_dir = str(task_output_dir)
    os.makedirs(task_output_dir, exist_ok=True)
    if not callable(getattr(adapter, "capture_current_parameter_state", None)) or not callable(
            getattr(adapter, "restore_parameter_state", None)):
        raise ValueError("Optimization requires an adapter with complete parameter capture/restore")
    adapter.config.setdefault("param_names", param_mgr.get_param_names())
    adapter.config.setdefault("param_units", [item.get("unit", "mm") for item in config["parameters"]])
    if list(adapter.config["param_names"]) != param_mgr.get_param_names():
        raise ValueError("Optimization parameter names differ from the adapter contract")
    baseline = adapter.capture_current_parameter_state()
    if not isinstance(baseline, dict) or not baseline or set(param_mgr.get_param_names()) - baseline.keys():
        raise ValueError("Optimization requires a complete baseline with all configured parameters")
    executor = CaseExecutor(adapter, fitness_calc, config, baseline, journal,
                            metrics_collector=_collect_optional_metrics)
    adapter._case_executor = executor
    def enrich_for_parameters(extra, params):
        geometry_extra = _build_geometry_metric_extra(
            params=params, param_names=param_mgr.get_param_names(),
            baseline_state=geometry_baseline_state, geometry_cfg=geometry_metric_config,
            adapter=adapter)
        if geometry_extra:
            extra.update(geometry_extra)
    periodic_exports = []
    export_solve_attempts = 0
    last_periodic_export_sim = 0

    def begin_export_solve():
        nonlocal export_solve_attempts
        export_solve_attempts += 1
        adapter.last_task_outcome["export_verification_solve_attempts"] = export_solve_attempts

    def export_periodic_best():
        nonlocal last_periodic_export_sim
        if not save_interval or best_params is None or sim_count // save_interval <= last_periodic_export_sim // save_interval:
            return
        last_periodic_export_sim = sim_count
        if budget_exhausted(end_at, time.time(), longest_simulation, opt_config.get("save_best_on_exit", True)):
            journal.append({"record_type": "best_model_export_skipped", "search_simulations": sim_count,
                            "reason": "time_budget"})
            return
        path = Path(task_output_dir) / f"best_after_{sim_count}_sim.aedt"
        try:
            # Negative IDs are reserved for periodic verification, outside the
            # positive search-attempt IDs and the final verification ID.
            params, cost, _ = _revalidate_export_candidate(
                config, adapter, param_mgr, fitness_calc, best_params, executor=executor,
                case_id=-(len(periodic_exports) + 1), enrich_metrics=enrich_for_parameters,
                case_role="periodic_export_verification",
                case_fields={"search_simulations": sim_count, "best_source_sim_id": best_sim_id},
                before_solve=begin_export_solve)
            _sync_adapter_best_state(adapter, params, cost)
            if not adapter.save_best_result(output_path=str(path)):
                raise RuntimeError("Periodic best project could not be saved")
            event = {"record_type": "best_model_exported", "export_kind": "periodic",
                     "search_simulations": sim_count, "best_source_sim_id": best_sim_id,
                     "params": params.tolist(), "cost": cost, "path": str(path)}
            periodic_exports.append(event)
            adapter.last_task_outcome["periodic_exports"] = periodic_exports.copy()
            journal.append(event)
        finally:
            # Optimization continues after a periodic snapshot, so normal case
            # isolation still applies. Final export has no such restoration.
            executor.restore()
            _sync_adapter_best_state(adapter, best_params, best_cost)
    manifest = build_execution_manifest(config, adapter)
    adapter.execution_fingerprint = manifest["fingerprint"]
    with Path(task_output_dir, "execution_manifest.json").open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2, allow_nan=False)
    history_load_summary = {
        "requested_sources": 0,
        "accepted_sources": 0,
        "rejected_sources": 0,
        "loaded": 0,
        "skipped_out_of_bounds": 0,
        "skipped_invalid_rows": 0,
    }
    if str(config.get("algorithm", {}).get("method", "")).strip().lower() == "bo":
        history_load_summary = _load_manual_bo_history(
            config, algorithm, param_mgr, manifest=manifest, fitness_calc=fitness_calc)
    with Path(task_output_dir, "history_import_summary.json").open("x", encoding="utf-8") as stream:
        json.dump({key: value for key, value in history_load_summary.items() if key != "raw_history"},
                  stream, ensure_ascii=False, indent=2, allow_nan=False)

    logger = OptimizationLogger(os.path.join(task_output_dir, task_history_file_name(task_type)), param_mgr.get_param_names())
    resources.append(logger)
    raw_enabled = output_config.get("save_data", output_config.get("save_csv", True))
    data_logger = SimulationDataLogger(
        task_output_dir,
        param_mgr.get_param_names(),
        task_type=task_type,
        enabled=raw_enabled,
        storage_format=output_config.get("raw_data_format", "jsonl"),
    )
    resources.append(data_logger)
    fitness_trend_enabled = output_config.get("plot_fitness_trend", True)
    fitness_trend_path = os.path.join(task_output_dir, task_fitness_trend_file_name(task_type))
    pareto_front_plot_path = os.path.join(task_output_dir, task_pareto_front_file_name(task_type, "png"))
    dashboard_writer = None
    try:
        dashboard_writer = DashboardStateWriter(task_output_dir, config)
        if history_load_summary["loaded"] > 0:
            dashboard_writer.append_event(
                f"Loaded {history_load_summary['loaded']} BO history points",
                "info",
            )
    except Exception as exc:
        print(f"Dashboard snapshot writer disabled: {exc}")

    adapter._task_dashboard_writer = dashboard_writer

    best_cost = float("inf")
    best_params = None
    best_result = None
    best_sim_id = None
    iteration = 0
    patience_counter = 0
    sim_count = 0
    solve_attempts = 0
    simulation_cache: dict[tuple[str, ...], dict] = {}
    for data in history_load_summary.get("raw_history", []):
        simulation_cache[_simulation_cache_key(data["params"], param_mgr, adapter)] = data
    attempt_count = 0
    failure_count = 0
    consecutive_failures = 0
    termination_reason = "max_iters"
    raw_fitness_history: list[float] = []
    stop_requested = False
    metric_collection_failed = False

    save_config_snapshot(task_output_dir, config)

    print(f"\nStart optimization: {config.get('name', 'optimization')}")
    print(f"Algorithm: {algorithm.name} | Target: {_describe_target(target_config)}")
    if history_load_summary["requested_sources"]:
        print(
            "History warm-start: "
            f"loaded={history_load_summary['loaded']}, "
            f"accepted_sources={history_load_summary['accepted_sources']}, "
            f"rejected_sources={history_load_summary['rejected_sources']}, "
            f"skipped_out_of_bounds={history_load_summary['skipped_out_of_bounds']}, "
            f"skipped_invalid_rows={history_load_summary['skipped_invalid_rows']}"
        )
    if max_simulations is not None:
        print(f"Max simulations: {max_simulations}")
    print(f"Cache cleanup every: {cleanup_every}")
    print(f"Output dir: {task_output_dir}\n")
    is_multi_objective = bool(getattr(algorithm, "is_multi_objective", False))

    if bool(opt_config.get("initial_cleanup_solution", False)):
        print("Initial solution cleanup requested before the first solve")
        _cleanup_aedt_cache(
            adapter,
            attempts=int(opt_config.get("initial_cleanup_attempts", 3)),
            initial_wait=float(opt_config.get("initial_cleanup_wait", 1.0)),
            retry_wait=float(opt_config.get("initial_cleanup_retry_wait", 2.0)),
        )

    while iteration < max_iters:
        if dashboard_writer is not None and getattr(dashboard_writer, "is_stop_requested", None):
            try:
                if dashboard_writer.is_stop_requested():
                    print("\nStop requested from dashboard; waiting for current simulation to finish.")
                    termination_reason = "user_stop"
                    break
            except Exception as exc:
                print(f"Dashboard stop-state check failed: {exc}")
        effective_iteration = iteration + 1
        sim_limit_reached = False

        try:
            candidates, batch_mode = _get_candidate_batch(algorithm)
            if not len(candidates) or candidates.shape != (len(candidates), param_mgr.n_params):
                raise ValueError("Algorithm candidate dimension differs from the parameter contract")
        except DuplicateCandidateExhausted as exc:
            print(f"\n{exc}")
            termination_reason = "duplicate_retries"
            break
        if seed_point is not None and effective_iteration == 1:
            candidates = np.asarray(candidates, dtype=float)
            if candidates.ndim == 1:
                candidates = candidates[np.newaxis, :]
            try:
                seed_idx = None
                for idx, candidate in enumerate(candidates):
                    if np.allclose(candidate, seed_point, atol=1e-12, rtol=0.0):
                        seed_idx = idx
                        break
                if seed_idx is not None and seed_idx != 0:
                    candidates[[0, seed_idx]] = candidates[[seed_idx, 0]]
                else:
                    candidates[0] = seed_point.copy()
            except Exception as exc:
                print(f"Seed-first reorder failed: {exc}")
        round_results = []
        round_has_new_simulation = False
        round_improved = False
        round_target_met = False
        round_stage_met = False
        retry_current_iteration = False

        for idx, candidate in enumerate(candidates):
            if max_simulations is not None and solve_attempts >= max_simulations:
                sim_limit_reached = True
                break
            if attempt_count >= max_attempts:
                termination_reason = "attempt_budget"
                break
            if consecutive_failures >= max_failures:
                termination_reason = "failure_budget"
                break
            if budget_exhausted(end_at, time.time(), longest_simulation, opt_config.get("save_best_on_exit", True)):
                termination_reason = "time_budget"
                break
            params = _project_search_params(
                np.array(candidate, dtype=float),
                param_mgr,
                continuous_search=continuous_search,
            )
            sim_params = param_mgr.quantize_manufacturing(params) if continuous_search else params.copy()
            sim_params = param_mgr.repair_constraints(sim_params)
            attempt_count += 1
            journal.append({"record_type": "case_started", "case_id": attempt_count,
                            "iteration": effective_iteration, "params": sim_params.tolist()})

            if not param_mgr.check_constraints(sim_params):
                failure_count += 1
                consecutive_failures += 1
                journal.append({"record_type": "case_finished", "case_id": attempt_count,
                                "status": "failed", "failure_reason": "constraints"})
                if batch_mode:
                    round_results.append(_failed_batch_result(sim_params, idx, "constraints", fitness_calc))
                continue

            _sync_candidate_state(algorithm, idx, sim_params)

            cache_key = _simulation_cache_key(sim_params, param_mgr, adapter)
            cached_fitness = simulation_cache.get(cache_key)
            if cached_fitness is not None:
                if algo_method == "bo" and hasattr(algorithm, "register_existing_candidate"):
                    try:
                        algorithm.register_existing_candidate(params)
                    except Exception as exc:
                        print(f"BO cache-reject registration failed: {exc}")
                    retry_current_iteration = True
                    journal.append({"record_type": "case_finished", "case_id": attempt_count,
                                    "status": "cache_rejected", "source_sim_id": cached_fitness["source_sim_id"]})
                    print(f"[Cache] iter={effective_iteration}, rejected cached BO candidate for {list(cache_key)}")
                    break
                reused = fitness_calc.calculate(cached_fitness["freqs"], cached_fitness["s11"],
                    cached_fitness["s12"], extra_metrics=copy.deepcopy(cached_fitness["extra_metrics"]))
                if not getattr(reused, "valid", True) or not np.isfinite(reused.cost):
                    failure_count += 1
                    consecutive_failures += 1
                    journal.append({"record_type": "case_finished", "case_id": attempt_count,
                                    "status": "failed", "failure_reason": reused.failure_reason})
                    if batch_mode:
                        round_results.append(_failed_batch_result(sim_params, idx, "invalid_cache", fitness_calc))
                    continue
                reused.params = sim_params.copy()
                consecutive_failures = 0
                reused.source_sim_id = cached_fitness["source_sim_id"]
                journal.append({"record_type": "case_finished", "case_id": attempt_count,
                                "status": "cache_reused", "source_sim_id": reused.source_sim_id,
                                "cost": float(reused.cost), "stage_index": getattr(reused, "stage_index", None)})
                if batch_mode:
                    reused.individual_idx = idx
                    reused.particle_idx = idx
                round_results.append(reused)
                if not is_multi_objective and adapter.update_best(sim_params, reused.cost):
                    best_params, best_cost, best_result = sim_params.copy(), reused.cost, reused
                    best_sim_id = reused.source_sim_id
                    round_improved = True
                    patience_counter = 0
                round_stage_met = round_stage_met or getattr(reused, "stage_met", False)
                print(f"[Cache] iter={effective_iteration}, reuse sim={getattr(reused, 'source_sim_id', 'n/a')} for {list(cache_key)}")
                if reused.target_met and stop_on_target:
                    round_target_met = True
                    break
                continue

            next_sim_id = sim_count + 1
            def begin_solve():
                _print_simulation_header(next_sim_id, effective_iteration, setup_name, sim_params,
                                         param_mgr.get_param_names(), cleanup_every)
                if dashboard_writer is not None:
                    try:
                        dashboard_writer.begin_simulation(sim_id=next_sim_id, iter_id=effective_iteration)
                    except Exception as exc:
                        print(f"Dashboard simulation timer start failed: {exc}")

            def enrich_metrics(extra):
                enrich_for_parameters(extra, sim_params)

            outcome = executor.execute(
                attempt_count, dict(zip(param_mgr.get_param_names(), sim_params.tolist())),
                fields={"iteration": effective_iteration, "params": sim_params.tolist(),
                        "source_sim_id": next_sim_id, "case_role": "optimization"},
                parameter_vector=sim_params, before_solve=begin_solve,
                enrich_metrics=enrich_metrics, already_started=True)
            solve_attempts += int(outcome.simulation_attempted)
            if outcome.simulation_attempted:
                longest_simulation = max(longest_simulation, outcome.duration_seconds)
            if outcome.result_acquired:
                sim_count += 1
                round_has_new_simulation = True
            if outcome.status != "completed":
                failure_count += 1
                consecutive_failures += 1
                if outcome.failure_phase == "metrics":
                    termination_reason = "metric_collection_failed"
                    metric_collection_failed = True
                    break
                if batch_mode:
                    round_results.append(_failed_batch_result(sim_params, idx, outcome.failure_reason, fitness_calc))
                continue
            freqs, s11, s12 = outcome.freqs, outcome.s11, outcome.s12
            extra_metrics, fitness = outcome.extra_metrics, outcome.fitness
            consecutive_failures = 0
            bo_diagnostics = None
            if algo_method == "bo" and hasattr(algorithm, "attach_result_diagnostics"):
                try:
                    bo_diagnostics = algorithm.attach_result_diagnostics(fitness)
                except Exception as exc:
                    print(f"BO diagnostics attach failed: {exc}")
            fitness.params = sim_params.copy()
            fitness.source_sim_id = sim_count
            round_stage_met = round_stage_met or getattr(fitness, "stage_met", False)

            if batch_mode:
                fitness.individual_idx = idx
                fitness.particle_idx = idx

            simulation_cache[cache_key] = {
                "params": sim_params.copy(),
                "freqs": np.asarray(freqs).copy(), "s11": np.asarray(s11).copy(),
                "s12": np.asarray(s12).copy() if s12 is not None else None,
                "extra_metrics": copy.deepcopy(extra_metrics), "source_sim_id": sim_count,
            }
            round_results.append(fitness)

            is_checkpoint = bool(save_interval and sim_count % save_interval == 0)
            logger.log(
                effective_iteration,
                fitness.cost,
                fitness.s11_max,
                fitness.bandwidth,
                fitness.s12_max,
                fitness.target_met,
                sim_params,
                is_checkpoint,
                component_costs=getattr(fitness, "component_costs", {}),
                raw_metrics=getattr(fitness, "raw_metrics", {}),
                adaptive_scales=getattr(fitness, "adaptive_scales", {}),
                objectives=getattr(fitness, "objectives", []),
                constraint_violation=getattr(fitness, "constraint_violation", None),
                bo_diagnostics=bo_diagnostics,
            )
            data_logger.log_simulation(effective_iteration, sim_params, freqs, s11, s12, extra_metrics=extra_metrics)
            raw_fitness_history.append(float(fitness.cost))
            if fitness_trend_enabled and not is_multi_objective:
                try:
                    plot_fitness_trend(raw_fitness_history, fitness_trend_path)
                except Exception as exc:
                    print(f"Fitness trend plot update failed: {exc}")
                    fitness_trend_enabled = False
            if dashboard_writer is not None:
                try:
                    dashboard_writer.record_simulation(
                        sim_id=sim_count,
                        iter_id=effective_iteration,
                        params=sim_params,
                        param_names=param_mgr.get_param_names(),
                        freqs=freqs,
                        s11=s11,
                        s12=s12,
                        fitness=fitness,
                        checkpoint=is_checkpoint,
                        stage_name=getattr(fitness, "stage_name", ""),
                    )
                except Exception as exc:
                    print(f"Dashboard snapshot update failed: {exc}")
                    dashboard_writer = None

            if cleanup_every and sim_count > 0 and sim_count % cleanup_every == 0:
                _cleanup_aedt_cache(adapter)

            if not is_multi_objective and adapter.update_best(sim_params, fitness.cost):
                best_cost = fitness.cost
                best_params = sim_params.copy()
                best_result = fitness
                best_sim_id = sim_count
                round_improved = True
                patience_counter = 0
                s12_text = f", s12={fitness.s12_max:.2f} dB" if fitness.s12_max is not None else ""
                print(
                    f"[Best] iter={effective_iteration}, sim={sim_count}, cost={fitness.cost:.4f}, "
                    f"s11={fitness.s11_max:.2f} dB{s12_text}"
                )

            if not is_multi_objective:
                export_periodic_best()

            if fitness.target_met and stop_on_target:
                round_target_met = True
                break

            if max_simulations is not None and solve_attempts >= max_simulations:
                sim_limit_reached = True
                break

            if dashboard_writer is not None and getattr(dashboard_writer, "is_stop_requested", None):
                try:
                    if dashboard_writer.is_stop_requested():
                        stop_requested = True
                        break
                except Exception as exc:
                    print(f"Dashboard stop-state check failed: {exc}")

        batch_complete = batch_mode and len(round_results) == len(candidates)
        algorithm_update_ready = batch_complete if batch_mode else (round_has_new_simulation and bool(round_results))
        if round_results and algorithm_update_ready:
            try:
                if algo_method == "cmaes":
                    _penalize_failed_cma_results(round_results)
                algorithm.update(round_results)
            except Exception as e:
                raise RuntimeError(f"Algorithm update failed: {e}") from e
            else:
                if is_multi_objective and getattr(algorithm, "best_params", None) is not None:
                    best_params = np.asarray(algorithm.best_params, dtype=float).copy()
                    best_cost = float(getattr(algorithm, "best_cost", best_cost))
                    best_result = getattr(algorithm, "best_result", best_result)
                    best_sim_id = getattr(algorithm, "best_source_sim_id", None)
                    if best_sim_id is None and best_result is not None:
                        best_sim_id = getattr(best_result, "source_sim_id", None)
                    if getattr(algorithm, "last_front_updated", False) or getattr(algorithm, "last_representative_improved", False):
                        round_improved = True
                        patience_counter = 0
                        front_size = len(getattr(algorithm, "pareto_front", []) or [])
                        objectives = getattr(best_result, "objectives", []) if best_result is not None else []
                        print(
                            f"[Pareto] iter={effective_iteration}, sim={sim_count}, front={front_size}, "
                            f"source_sim={best_sim_id}, "
                            f"constraint={getattr(best_result, 'constraint_violation', 0.0):.4f}, "
                            f"objectives={objectives}"
                        )
                    if dashboard_writer is not None:
                        try:
                            dashboard_writer.update_pareto_front(algorithm.get_pareto_front())
                        except Exception as exc:
                            print(f"Dashboard Pareto update failed: {exc}")
                    if fitness_trend_enabled:
                        try:
                            plot_pareto_front(
                                algorithm.get_pareto_front(),
                                pareto_front_plot_path,
                                target_config.get("multi_objective", {}).get("objectives"),
                            )
                        except Exception as exc:
                            print(f"Pareto front plot update failed: {exc}")
                            fitness_trend_enabled = False

                if is_multi_objective:
                    # The representative best is selected by the completed
                    # population update; defer crossed intervals to that point.
                    export_periodic_best()

        if batch_mode and is_multi_objective and not batch_complete and round_results:
            finalize_partial = getattr(algorithm, "finalize_partial_batch", None)
            if callable(finalize_partial):
                finalize_partial(round_results)
                if getattr(algorithm, "best_result", None) is not None:
                    best_result = algorithm.best_result
                    best_params = np.asarray(algorithm.best_params, dtype=float).copy()
                    best_cost = float(algorithm.best_cost)
                    best_sim_id = algorithm.best_source_sim_id
                    journal.append({"record_type": "partial_batch_best_selected",
                                    "iteration": effective_iteration, "source_sim_id": best_sim_id,
                                    "params": best_params.tolist(), "cost": best_cost,
                                    "target_met": bool(getattr(best_result, "target_met", False))})

        if batch_mode:
            journal.append({"record_type": "batch_finished", "iteration": effective_iteration,
                            "planned_candidates": len(candidates), "evaluated_candidates": len(round_results),
                            "valid_candidates": sum(bool(getattr(item, "valid", True)) for item in round_results),
                            "complete": batch_complete, "algorithm_updated": bool(algorithm_update_ready)})

        if termination_reason in {"time_budget", "attempt_budget", "failure_budget"}:
            print(f"\nOptimization budget reached: {termination_reason}")
            break

        if stop_requested:
            print("\nStop requested from dashboard; ending after current simulation.")
            termination_reason = "user_stop"
            break

        if metric_collection_failed:
            break

        if retry_current_iteration:
            continue

        if sim_limit_reached:
            termination_reason = "max_simulations"
            break

        if round_target_met:
            print("\nTarget reached!")
            termination_reason = "target_met"
            break

        if algorithm_update_ready:
            iteration += 1
        else:
            if round_target_met:
                iteration += 1
            continue

        stage_advanced = False
        if round_stage_met and not round_target_met:
            if fitness_calc.advance_stage():
                stage_advanced = True
                next_stage = fitness_calc.active_stage
                algorithm, best_result, rescored_count = restart_stage(
                    config, param_mgr, fitness_calc, algorithm, simulation_cache, adapter,
                    factory=create_algorithm, cache_key=_simulation_cache_key)
                executor.calculator = fitness_calc
                adapter.active_algorithm = algorithm
                best_params = best_result.params.copy() if best_result is not None else None
                best_cost = float(best_result.cost) if best_result is not None else float("inf")
                best_sim_id = best_result.source_sim_id if best_result is not None else None
                _sync_adapter_best_state(adapter, best_params, best_cost)
                journal.append({"record_type": "stage_transition", "stage_index": fitness_calc.stage_index,
                                "stage_name": next_stage.name, "strategy": "rescore_and_restart",
                                "rescored_observations": rescored_count,
                                "best_params": best_params.tolist() if best_params is not None else None,
                                "best_cost": best_cost if best_params is not None else None})
                print(
                    f"\nStage advanced -> {next_stage.name}: "
                    f"S11<={next_stage.s11_target} dB"
                    + (
                        f", S12<={next_stage.s12_target} dB"
                        if getattr(next_stage, "s12_target", None) is not None
                        else ""
                    )
                    + f" in {next_stage.freq_band[0]}-{next_stage.freq_band[1]} GHz"
                )
                if dashboard_writer is not None:
                    try:
                        dashboard_writer.append_event(f"Stage advanced -> {next_stage.name}", "info")
                    except Exception:
                        pass
                round_improved = True
                patience_counter = 0

        advance_penalty = getattr(fitness_calc, "advance_penalty_epoch", None)
        if (not stage_advanced and not round_target_met and algorithm_update_ready
                and round_has_new_simulation and callable(advance_penalty)
                and advance_penalty(round_results)):
            algorithm, best_result, rescored_count = restart_stage(
                config, param_mgr, fitness_calc, algorithm, simulation_cache, adapter,
                factory=create_algorithm, cache_key=_simulation_cache_key)
            adapter.active_algorithm = algorithm
            best_params = best_result.params.copy() if best_result is not None else None
            best_cost = float(best_result.cost) if best_result is not None else float("inf")
            best_sim_id = best_result.source_sim_id if best_result is not None else None
            _sync_adapter_best_state(adapter, best_params, best_cost)
            journal.append({"record_type": "penalty_epoch_transition", "iteration": iteration,
                            "stage_index": fitness_calc.stage_index,
                            "adaptive_scales": fitness_calc.adaptive_scales.copy(),
                            "strategy": "rescore_and_restart", "rescored_observations": rescored_count,
                            "best_cost": best_cost if best_params is not None else None})
            # A changed scale is not evidence that a better physical case was found.

        if not round_improved and round_results:
            patience_counter += 1

        if sim_limit_reached:
            print(f"\nMax simulations reached: {max_simulations}")
            termination_reason = "max_simulations"
            break

        if early_stop_enabled and patience_counter >= patience:
            print(f"\nEarly stop: no improvement for {patience} rounds")
            termination_reason = "early_stop"
            break

    print(f"\nOptimization done | total sims: {sim_count} | best cost: {best_cost:.4f}")
    if best_params is not None:
        for name, val in zip(param_mgr.get_param_names(), best_params):
            print(f"  {name} = {val:.4f}")

    if opt_config.get("save_best_on_exit", True) and best_params is not None:
        export_params, export_cost, export_result = _revalidate_export_candidate(
            config=config,
            adapter=adapter,
            param_mgr=param_mgr,
            fitness_calc=fitness_calc,
            best_params=best_params,
            executor=executor, case_id=attempt_count + 1, enrich_metrics=enrich_for_parameters,
            before_solve=begin_export_solve,
        )
        if export_result is not None:
            best_result = export_result
        final_best_params = export_params if export_params is not None else best_params
        final_best_cost = export_cost if export_cost is not None else best_cost
        _sync_adapter_best_state(adapter, final_best_params, final_best_cost)
        if not adapter.save_best_result(output_dir=task_output_dir, sim_id=best_sim_id):
            raise RuntimeError("Verified best project could not be saved")
        adapter._optimization_export_saved = True
        best_params, best_cost = final_best_params, final_best_cost
    if is_multi_objective:
        _save_pareto_front(task_output_dir, algorithm, param_mgr.get_param_names(), task_type=task_type)
        if fitness_trend_enabled:
            try:
                plot_pareto_front(
                    algorithm.get_pareto_front(),
                    pareto_front_plot_path,
                    target_config.get("multi_objective", {}).get("objectives"),
                )
            except Exception as exc:
                print(f"Pareto front plot finalize failed: {exc}")

    failed = termination_reason in {"metric_collection_failed", "failure_budget"} or (
        not simulation_cache and termination_reason not in {"user_stop", "time_budget"})
    final_status = "Failed" if failed else ("Completed" if termination_reason in {"max_iters", "target_met"} else "Stopped")
    adapter.last_task_outcome = {
        "status": final_status, "termination_reason": termination_reason,
        "attempts": attempt_count, "failures": failure_count, "simulations": sim_count,
        "solve_attempts": solve_attempts,
        "valid_simulations": len(simulation_cache),
        "best_params": best_params.tolist() if best_params is not None else None,
        "best_cost": float(best_cost) if best_params is not None else None,
        "target_met": bool(getattr(best_result, "target_met", False)),
        "export_verified": bool(opt_config.get("save_best_on_exit", True) and best_params is not None),
        "periodic_exports": periodic_exports,
        "export_verification_solve_attempts": export_solve_attempts,
        "total_solve_attempts": solve_attempts + export_solve_attempts,
    }
    if dashboard_writer is not None:
        details = {"target_met": "Target reached", "max_iters": "Optimization finished",
                   "max_simulations": "Max simulations reached", "time_budget": "Time budget reached",
                   "early_stop": "Early stop after no improvement", "user_stop": "Stop requested from dashboard",
                   "duplicate_retries": "Duplicate candidate retries exhausted",
                   "failure_budget": "Consecutive failure limit reached",
                   "attempt_budget": "Candidate attempt limit reached",
                   "metric_collection_failed": "Required metric collection failed"}
        adapter._task_completion_message = details.get(termination_reason, "Optimization finished")
    return best_params, best_cost, best_result


def run_single_simulation(config: dict, adapter: HFSSAdapter):
    """Run one read-only simulation."""
    output_config = config.get("output", {})
    target_config = config.get("target", {})
    task_name = config.get("name", "task")
    opt_config = config.get("optimization", {})
    run_stamp = opt_config.get("run_stamp")
    task_type = normalize_task_type(config)

    print("\nRun one simulation...")
    simulate_started_at = time.time()

    freqs, s11, s12 = adapter.simulate()
    if freqs is None or s11 is None:
        print("Simulation failed")
        return False

    task_output_dir = opt_config.get("task_output_dir") or resolve_task_output_dir(config, run_stamp=run_stamp)
    task_output_dir = str(task_output_dir)
    os.makedirs(task_output_dir, exist_ok=True)

    params = adapter.get_parameters()
    param_names = adapter.config.get("param_names", [])
    fitness_calc = FitnessCalculator(
        target_config.get("freq_band", [0, 0]),
        target_config.get("s11_threshold", -10),
        target_config.get("s12_threshold", target_config.get("s21_threshold")),
        target_config.get("bandwidth_target"),
        target_config.get("gain_min"),
        target_config.get("stages"),
        objective_mode=target_config.get("objective_mode", "legacy"),
        fitness_config=target_config.get("fitness"),
        multi_objective_config=target_config.get("multi_objective"),
        s11_profile=target_config.get("s11_profile"),
        s11_lower_bands=target_config.get("s11_lower_bands"),
    )

    raw_enabled = output_config.get("save_data", output_config.get("save_csv", True))
    data_logger = SimulationDataLogger(
        task_output_dir,
        param_names,
        task_type=task_type,
        enabled=raw_enabled,
        storage_format=output_config.get("raw_data_format", "jsonl"),
    )
    dashboard_writer = None
    try:
        dashboard_writer = DashboardStateWriter(task_output_dir, config)
    except Exception as exc:
        print(f"Dashboard snapshot writer disabled: {exc}")
    extra_metrics = {}
    try:
        extra_metrics = _collect_optional_metrics(config, adapter)
    except Exception as exc:
        print(f"Optional metric collection failed: {exc}")
        extra_metrics = {}

    data_logger.log_simulation(1, params, freqs, s11, s12, extra_metrics=extra_metrics)
    if dashboard_writer is not None:
        try:
            fitness = fitness_calc.calculate(freqs, s11, s12, extra_metrics=extra_metrics)
            dashboard_writer.current_sim_started_at = simulate_started_at
            dashboard_writer.record_simulation(
                sim_id=1,
                iter_id=1,
                params=params,
                param_names=param_names,
                freqs=freqs,
                s11=s11,
                s12=s12,
                fitness=fitness,
                checkpoint=False,
                stage_name=getattr(fitness, "stage_name", ""),
            )
            dashboard_writer.finalize("Completed", "Read-only run")
        except Exception as exc:
            print(f"Dashboard snapshot update failed: {exc}")
            dashboard_writer = None
    data_logger.close()

    save_config_snapshot(task_output_dir, config)

    if output_config.get("plot_s11", False):
        plot_path = os.path.join(task_output_dir, f"{task_name}_s11.png")
        plot_s11(freqs, s11, plot_path)

    print(f"Saved to: {task_output_dir}")
    return True


def run_task(
    config_source: str | os.PathLike[str] | dict,
    *,
    run_stamp: str | None = None,
    task_output_dir: str | os.PathLike[str] | None = None,
    task_work_dir: str | os.PathLike[str] | None = None,
):
    """Run a config-backed task inside the current process."""
    config_path = config_source if not isinstance(config_source, dict) else CONFIG_FILE
    config = config_source if isinstance(config_source, dict) else load_config(config_source)
    task_type = validate_task_config(config)
    config["task_type"] = task_type
    if task_type == "opt":
        _apply_default_single_objective_fitness_config(config)
    task_name = resolve_task_name(config, config_path)
    opt_config = config.get("optimization", {})
    resolved_run_stamp = resolve_run_stamp(run_stamp or opt_config.get("run_stamp"))
    resolved_task_output_dir = task_output_dir or os.environ.get("PY_AEDT_TASK_OUTPUT_DIR") or resolve_task_output_dir(
        config,
        run_stamp=resolved_run_stamp,
        task_name=task_name,
    )
    resolved_task_work_dir = task_work_dir or resolve_task_work_dir(
        config,
        run_stamp=resolved_run_stamp,
        task_name=task_name,
    )
    opt_config["run_stamp"] = resolved_run_stamp
    opt_config["task_output_dir"] = str(resolved_task_output_dir)
    opt_config["work_dir"] = str(resolved_task_work_dir)
    save_config_snapshot(resolved_task_output_dir, config)

    adapter = create_adapter(config, opt_config, task_name)

    if not adapter.connect():
        print("Connection failed")
        return 1

    try:
        if task_type == "sweep":
            result = run_hfss_sweep(config, adapter)
            if isinstance(result, dict) and result.get("status") == "Failed":
                return 1
        elif task_type == "val":
            result = run_val_cases(config, adapter)
            if isinstance(result, dict) and result.get("status") == "Failed":
                return 1
        elif task_type == "opt":
            param_mgr = ParameterManager(config["parameters"])

            target = config["target"]
            fitness_calc = FitnessCalculator(
                freq_band=tuple(target["freq_band"]),
                s11_target=target.get("s11_threshold", -10),
                s12_target=target.get("s12_threshold", target.get("s21_threshold")),
                bandwidth_target=target.get("bandwidth_target"),
                gain_target=target.get("gain_min"),
                stages=target.get("stages"),
                objective_mode=target.get("objective_mode", "legacy"),
                fitness_config=target.get("fitness"),
                multi_objective_config=target.get("multi_objective"),
                s11_profile=target.get("s11_profile"),
                s11_lower_bands=target.get("s11_lower_bands"),
            )

            param_names = [p["name"] for p in config["parameters"]]
            param_units = [p.get("unit", "mm") for p in config["parameters"]]
            param_resolutions = [p.get("resolution") for p in config["parameters"]]
            adapter.config["param_names"] = param_names
            adapter.config["param_units"] = param_units
            adapter.config["param_resolutions"] = param_resolutions

            algorithm = create_algorithm(config, param_mgr)
            if fitness_calc.is_multi_objective and not getattr(algorithm, "is_multi_objective", False):
                raise ValueError("target.multi_objective.enabled=true requires a multi-objective algorithm such as nsga2.")
            if getattr(algorithm, "is_multi_objective", False) and not fitness_calc.is_multi_objective:
                raise ValueError("Multi-objective algorithms require target.multi_objective.enabled=true.")
            run_optimization(config, adapter, param_mgr, fitness_calc, algorithm)
            if getattr(adapter, "last_task_outcome", {}).get("status") == "Failed":
                return 1
        else:
            run_single_simulation(config, adapter)
    finally:
        adapter.disconnect()
    return 0


def _apply_default_single_objective_fitness_config(config: dict) -> None:
    """Choose a target-owned scalarization independently of the search algorithm."""
    target = config.get("target")
    if not isinstance(target, dict):
        return

    if str(target.get("objective_mode", "") or "").strip().lower() == "legacy":
        return

    multi_objective = target.get("multi_objective") or {}
    if bool(multi_objective.get("enabled", False)):
        return

    target["objective_mode"] = str(target.get("objective_mode") or "algorithm_aware").strip().lower()
    if target["objective_mode"] == "legacy":
        return


    fitness_cfg = target.get("fitness")
    if fitness_cfg is None:
        fitness_cfg = {}
        target["fitness"] = fitness_cfg
    elif not isinstance(fitness_cfg, dict):
        return

    if "single_objective_strategy" not in fitness_cfg:
        fitness_cfg.setdefault("scalarization", "weighted_metrics")
    fitness_cfg.setdefault("adaptive_penalty", False)
