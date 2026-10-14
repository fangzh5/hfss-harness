from pathlib import Path
import sys
from types import SimpleNamespace
import json
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from optimizer import task_runner
from optimizer.algorithms.bo import DuplicateCandidateExhausted
from fake_parameter_state import FakeParameterState


class DummyAdapter:
    def __init__(self):
        self.config = {}
        self.connect_calls = 0
        self.disconnect_calls = 0

    def connect(self):
        self.connect_calls += 1
        return True

    def disconnect(self):
        self.disconnect_calls += 1


def test_create_algorithm_builds_cmaes_with_explicit_initial_point(monkeypatch):
    config = {
        "optimization": {"initial_point": [1.0, 2.0]},
        "parameters": [
            {"name": "x", "min": 0.0, "max": 2.0, "resolution": 0.01},
            {"name": "y", "min": 1.0, "max": 3.0, "resolution": 0.01},
        ],
        "algorithm": {
            "method": "cmaes",
            "mode": "local",
            "advanced": {"sigma0": 0.08, "seed": 2026},
        },
    }
    captured = {}

    class CapturingCMAES:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(task_runner, "CMAESOptimizer", CapturingCMAES)
    param_mgr = task_runner.ParameterManager(config["parameters"])

    task_runner.create_algorithm(config, param_mgr)

    assert captured["bounds"] == [(0.0, 2.0), (1.0, 3.0)]
    assert np.allclose(captured["initial_point"], np.array([1.0, 2.0]))
    assert captured["mode"] == "local"
    assert captured["sigma0"] == pytest.approx(0.08)
    assert captured["seed"] == 2026


def test_create_algorithm_leaves_missing_cmaes_initial_point_for_center_default(monkeypatch):
    config = {
        "optimization": {},
        "parameters": [
            {"name": "x", "min": 0.0, "max": 2.0, "resolution": 0.01},
        ],
        "algorithm": {"method": "cmaes"},
    }
    captured = {}

    class CapturingCMAES:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(task_runner, "CMAESOptimizer", CapturingCMAES)
    param_mgr = task_runner.ParameterManager(config["parameters"])

    task_runner.create_algorithm(config, param_mgr)

    assert captured["initial_point"] is None
    assert captured["mode"] == "local"
    assert captured["sigma0"] is None
    assert captured["seed"] is None


def test_cmaes_defaults_to_algorithm_independent_scalar_fitness():
    config = {
        "target": {"freq_band": [54.0, 66.0], "s11_threshold": -10},
        "algorithm": {"method": "cmaes"},
    }

    task_runner._apply_default_single_objective_fitness_config(config)

    assert config["target"]["fitness"]["scalarization"] == "weighted_metrics"


def test_run_task_dispatches_sweep(monkeypatch, tmp_path):
    config = {
        "name": "demo_sweep",
        "task_type": "sweep",
        "optimization": {},
        "study": {
            "variables": [
                {"name": "strip_l", "start": 0.1, "stop": 0.2, "step": 0.1},
            ]
        },
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(__import__("json").dumps(config), encoding="utf-8")

    adapter = DummyAdapter()
    seen = {}

    monkeypatch.setattr(task_runner, "create_adapter", lambda config, opt_config=None, task_name=None: adapter)
    monkeypatch.setattr(task_runner, "run_hfss_sweep", lambda config, adapter: seen.setdefault("branch", "sweep"))
    monkeypatch.setattr(task_runner, "save_config_snapshot", lambda output_dir, config: seen.setdefault("saved", str(output_dir)))

    exit_code = task_runner.run_task(str(config_path))

    assert exit_code == 0
    assert seen["branch"] == "sweep"
    assert "saved" in seen
    assert adapter.connect_calls == 1
    assert adapter.disconnect_calls == 1


def test_simulation_data_logger_writes_jsonl_record(tmp_path):
    logger = task_runner.SimulationDataLogger(
        output_dir=str(tmp_path),
        param_names=["p1"],
        task_type="opt",
        enabled=True,
        storage_format="jsonl",
    )

    try:
        logger.log_simulation(
            1,
            np.array([0.15]),
            np.array([54.0, 55.0]),
            np.array([-8.0, -9.0]),
            None,
            extra_metrics={
                "bo_diagnostics": {
                    "phase": "bo",
                    "candidate_source": "fallback_random",
                    "pred_mean": 1.2,
                    "pred_std": 0.4,
                    "abs_error": 0.3,
                    "summary": {
                        "observations": 2,
                        "mae": 0.35,
                        "coverage_2sigma": 1.0,
                    },
                }
            },
        )
    finally:
        logger.close()

    raw_path = tmp_path / "opt_data.jsonl"
    assert raw_path.exists()
    lines = raw_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    payload = __import__("json").loads(lines[0])
    assert payload["bo_diagnostics"]["phase"] == "bo"
    assert payload["bo_diagnostics"]["candidate_source"] == "fallback_random"
    assert payload["bo_diagnostics"]["summary"]["mae"] == 0.35


class DummyOptAdapter(FakeParameterState, DummyAdapter):
    def __init__(self):
        super().__init__()
        self.current_params = None
        self.best_params = None
        self.best_fitness = float("inf")

    def set_parameters(self, params):
        self.current_params = np.asarray(params, dtype=float).copy()
        return True

    def simulate(self):
        cost = float(np.sum(np.square(self.current_params)))
        return np.array([60.0]), np.array([-cost]), None

    def update_best(self, params, cost):
        if cost < self.best_fitness:
            self.best_fitness = float(cost)
            self.best_params = np.asarray(params, dtype=float).copy()
            return True
        return False

    def save_best_result(self, *args, **kwargs):
        return True


class DummyFitnessCalculator:
    is_multi_objective = False

    def calculate(self, freqs, s11, s12, extra_metrics=None):
        cost = abs(float(s11[0]))
        return SimpleNamespace(
            cost=cost,
            s11_max=float(s11[0]),
            bandwidth=None,
            s12_max=None,
            target_met=cost < 0.02,
            stage_met=False,
        )


class DummyRepeatedCandidateAlgorithm:
    name = "DummyRepeat"
    is_multi_objective = False

    def __init__(self):
        self._suggestions = [
            np.array([0.2], dtype=float),
            np.array([0.2], dtype=float),  # cache hit; should not consume effective iteration
            np.array([0.3], dtype=float),
        ]
        self.update_calls = 0

    def suggest(self):
        if self._suggestions:
            return self._suggestions.pop(0).copy()
        return np.array([0.2], dtype=float)

    def update(self, fitness_results):
        self.update_calls += 1


class DummyDuplicateExhaustedAlgorithm:
    name = "DummyDuplicateExhausted"
    is_multi_objective = False

    def suggest(self):
        raise DuplicateCandidateExhausted("Unable to find a new BO candidate after 3 retries.")

    def update(self, fitness_results):
        pass


class DummyCacheRejectingBOAlgorithm:
    name = "BO"
    is_multi_objective = False

    def __init__(self):
        self._phase = 0
        self.update_calls = 0
        self.rejected_candidates = []

    def suggest(self):
        if self._phase == 0:
            self._phase = 1
            return np.array([0.2], dtype=float)
        if self._phase == 1:
            return np.array([0.2], dtype=float)
        return np.array([0.3], dtype=float)

    def register_existing_candidate(self, params):
        self.rejected_candidates.append(float(np.asarray(params, dtype=float)[0]))
        self._phase = 2

    def update(self, fitness_results):
        self.update_calls += 1


class DummyCMAESBatchAlgorithm:
    name = "CMA-ES"
    is_multi_objective = False

    def __init__(self, candidates):
        self.candidates = np.asarray(candidates, dtype=float)
        self.results = None
        self.update_calls = 0

    def suggest_population(self):
        return self.candidates.copy()

    def update(self, fitness_results):
        self.update_calls += 1
        self.results = list(fitness_results)


class DummyPartiallyFailingAdapter(DummyOptAdapter):
    def set_parameters(self, params):
        values = np.asarray(params, dtype=float)
        if values[0] > 0.5:
            return False
        return super().set_parameters(values)


class DummyAlwaysFailingAdapter(DummyOptAdapter):
    def simulate(self):
        return None, None, None


class DummyCountingAdapter(DummyOptAdapter):
    def __init__(self):
        super().__init__()
        self.sim_calls = 0

    def simulate(self):
        self.sim_calls += 1
        return super().simulate()


def test_run_optimization_does_not_spend_iteration_budget_on_cached_reuse(tmp_path):
    config = {
        "name": "demo_cached_iteration_budget",
        "task_type": "opt",
        "parameters": [
            {"name": "x", "min": 0.0, "max": 1.0, "resolution": 0.01},
        ],
        "target": {
            "freq_band": [54.0, 66.0],
            "s11_threshold": -10,
        },
        "algorithm": {
            "method": "de",
            "max_iterations": 2,
            "max_simulations": 5,
            "early_stop_patience": 0,
        },
        "optimization": {
            "save_best_on_exit": False,
            "save_interval": 1,
            "task_output_dir": str(tmp_path / "run"),
            "run_stamp": "test",
        },
        "output": {
            "save_data": False,
        },
        "simulator": {
            "hfss": {
                "setup_name": "Setup1",
            }
        },
    }

    adapter = DummyOptAdapter()
    param_mgr = task_runner.ParameterManager(config["parameters"])
    fitness_calc = DummyFitnessCalculator()
    algorithm = DummyRepeatedCandidateAlgorithm()

    best_params, best_cost, best_result = task_runner.run_optimization(
        config=config,
        adapter=adapter,
        param_mgr=param_mgr,
        fitness_calc=fitness_calc,
        algorithm=algorithm,
    )

    history_path = tmp_path / "run" / "opt_history.csv"
    lines = history_path.read_text(encoding="utf-8").strip().splitlines()

    # Header + two real simulations. The cached middle proposal must not consume
    # the second effective iteration budget slot.
    assert len(lines) == 3
    assert best_params[0] == 0.2
    assert best_cost == pytest.approx(0.04)
    assert best_result.cost == pytest.approx(0.04)
    assert algorithm.update_calls == 2


def test_run_optimization_stops_after_duplicate_retry_limit(tmp_path):
    config = {
        "name": "demo_duplicate_retry_limit",
        "task_type": "opt",
        "parameters": [
            {"name": "x", "min": 0.0, "max": 1.0, "resolution": 0.01},
        ],
        "target": {
            "freq_band": [54.0, 66.0],
            "s11_threshold": -10,
        },
        "algorithm": {
            "method": "bo",
            "max_iterations": 10,
            "max_simulations": 10,
            "max_duplicate_retries": 3,
            "early_stop_patience": 0,
        },
        "optimization": {
            "save_best_on_exit": False,
            "save_interval": 1,
            "task_output_dir": str(tmp_path / "run"),
            "run_stamp": "test",
        },
        "output": {
            "save_data": False,
        },
        "simulator": {
            "hfss": {
                "setup_name": "Setup1",
            }
        },
    }

    adapter = DummyOptAdapter()
    param_mgr = task_runner.ParameterManager(config["parameters"])
    fitness_calc = DummyFitnessCalculator()
    algorithm = DummyDuplicateExhaustedAlgorithm()

    task_runner.run_optimization(
        config=config,
        adapter=adapter,
        param_mgr=param_mgr,
        fitness_calc=fitness_calc,
        algorithm=algorithm,
    )

    history_path = tmp_path / "run" / "opt_history.csv"
    lines = history_path.read_text(encoding="utf-8").strip().splitlines()
    dashboard_state = json.loads((tmp_path / "run" / "opt_dashboard_state.json").read_text(encoding="utf-8"))

    assert len(lines) == 1
    assert dashboard_state["status"]["detail"] == "Duplicate candidate retries exhausted"


def test_run_optimization_completes_cmaes_batch_with_bad_cost_for_failed_candidate(tmp_path):
    config = {
        "name": "demo_cmaes_partial_failure",
        "task_type": "opt",
        "parameters": [
            {"name": "x", "min": 0.0, "max": 1.0, "resolution": 0.01},
        ],
        "target": {
            "freq_band": [54.0, 66.0],
            "s11_threshold": -10,
        },
        "algorithm": {
            "method": "cmaes",
            "max_iterations": 1,
            "early_stop_patience": 0,
        },
        "optimization": {
            "save_best_on_exit": False,
            "task_output_dir": str(tmp_path / "run"),
        },
        "output": {
            "save_data": False,
            "plot_fitness_trend": False,
        },
        "simulator": {"hfss": {"setup_name": "Setup1"}},
    }
    algorithm = DummyCMAESBatchAlgorithm([[0.2], [0.8]])

    task_runner.run_optimization(
        config=config,
        adapter=DummyPartiallyFailingAdapter(),
        param_mgr=task_runner.ParameterManager(config["parameters"]),
        fitness_calc=DummyFitnessCalculator(),
        algorithm=algorithm,
    )

    assert algorithm.update_calls == 1
    assert [result.individual_idx for result in algorithm.results] == [0, 1]
    assert algorithm.results[0].cost == pytest.approx(0.04)
    assert np.isfinite(algorithm.results[1].cost)
    assert algorithm.results[1].cost > algorithm.results[0].cost
    assert algorithm.results[1].failure_reason == "Parameter transaction failed"
    history_lines = (tmp_path / "run" / "opt_history.csv").read_text(encoding="utf-8").splitlines()
    assert len(history_lines) == 2


def test_run_optimization_advances_one_cmaes_generation_when_all_candidates_fail(tmp_path):
    config = {
        "name": "demo_cmaes_all_failed",
        "task_type": "opt",
        "parameters": [
            {"name": "x", "min": 0.0, "max": 1.0, "resolution": 0.01},
        ],
        "target": {
            "freq_band": [54.0, 66.0],
            "s11_threshold": -10,
        },
        "algorithm": {
            "method": "cmaes",
            "max_iterations": 1,
            "early_stop_patience": 0,
        },
        "optimization": {
            "save_best_on_exit": False,
            "task_output_dir": str(tmp_path / "run"),
        },
        "output": {
            "save_data": False,
            "plot_fitness_trend": False,
        },
        "simulator": {"hfss": {"setup_name": "Setup1"}},
    }
    algorithm = DummyCMAESBatchAlgorithm([[0.2], [0.8]])

    task_runner.run_optimization(
        config=config,
        adapter=DummyAlwaysFailingAdapter(),
        param_mgr=task_runner.ParameterManager(config["parameters"]),
        fitness_calc=DummyFitnessCalculator(),
        algorithm=algorithm,
    )

    assert algorithm.update_calls == 1
    assert len(algorithm.results) == 2
    assert all(result.failure_reason == "Solve or result acquisition failed" for result in algorithm.results)
    history_lines = (tmp_path / "run" / "opt_history.csv").read_text(encoding="utf-8").splitlines()
    assert len(history_lines) == 1


def test_run_optimization_reuses_cache_for_complete_cmaes_generations(tmp_path):
    config = {
        "name": "demo_cmaes_cache",
        "task_type": "opt",
        "parameters": [
            {"name": "x", "min": 0.0, "max": 1.0, "resolution": 0.01},
        ],
        "target": {
            "freq_band": [54.0, 66.0],
            "s11_threshold": -10,
        },
        "algorithm": {
            "method": "cmaes",
            "max_iterations": 2,
            "early_stop_patience": 0,
        },
        "optimization": {
            "save_best_on_exit": False,
            "task_output_dir": str(tmp_path / "run"),
        },
        "output": {
            "save_data": False,
            "plot_fitness_trend": False,
        },
        "simulator": {"hfss": {"setup_name": "Setup1"}},
    }
    algorithm = DummyCMAESBatchAlgorithm([[0.3034], [0.3010]])
    adapter = DummyCountingAdapter()

    task_runner.run_optimization(
        config=config,
        adapter=adapter,
        param_mgr=task_runner.ParameterManager(config["parameters"]),
        fitness_calc=DummyFitnessCalculator(),
        algorithm=algorithm,
    )

    assert adapter.sim_calls == 1
    assert algorithm.update_calls == 2
    assert len(algorithm.results) == 2
    assert [result.individual_idx for result in algorithm.results] == [0, 1]
    history_lines = (tmp_path / "run" / "opt_history.csv").read_text(encoding="utf-8").splitlines()
    assert len(history_lines) == 2


def test_run_optimization_does_not_update_cmaes_with_partial_target_met_batch(tmp_path):
    config = {
        "name": "demo_cmaes_partial_target",
        "task_type": "opt",
        "parameters": [
            {"name": "x", "min": 0.0, "max": 1.0, "resolution": 0.01},
        ],
        "target": {
            "freq_band": [54.0, 66.0],
            "s11_threshold": -10,
        },
        "algorithm": {
            "method": "cmaes",
            "max_iterations": 2,
            "early_stop_patience": 0,
        },
        "optimization": {
            "save_best_on_exit": False,
            "task_output_dir": str(tmp_path / "run"),
        },
        "output": {
            "save_data": False,
            "plot_fitness_trend": False,
        },
        "simulator": {"hfss": {"setup_name": "Setup1"}},
    }
    algorithm = DummyCMAESBatchAlgorithm([[0.1], [0.8]])

    task_runner.run_optimization(
        config=config,
        adapter=DummyCountingAdapter(),
        param_mgr=task_runner.ParameterManager(config["parameters"]),
        fitness_calc=DummyFitnessCalculator(),
        algorithm=algorithm,
    )

    assert algorithm.update_calls == 0


def test_run_optimization_retries_bo_cache_hit_with_new_candidate(tmp_path):
    config = {
        "name": "demo_bo_cache_retry",
        "task_type": "opt",
        "parameters": [
            {"name": "x", "min": 0.0, "max": 1.0, "resolution": 0.01},
        ],
        "target": {
            "freq_band": [54.0, 66.0],
            "s11_threshold": -10,
        },
        "algorithm": {
            "method": "bo",
            "max_iterations": 2,
            "max_simulations": 5,
            "early_stop_patience": 0,
        },
        "optimization": {
            "save_best_on_exit": False,
            "save_interval": 1,
            "task_output_dir": str(tmp_path / "run"),
            "run_stamp": "test",
        },
        "output": {
            "save_data": False,
        },
        "simulator": {
            "hfss": {
                "setup_name": "Setup1",
            }
        },
    }

    adapter = DummyOptAdapter()
    param_mgr = task_runner.ParameterManager(config["parameters"])
    fitness_calc = DummyFitnessCalculator()
    algorithm = DummyCacheRejectingBOAlgorithm()

    best_params, best_cost, best_result = task_runner.run_optimization(
        config=config,
        adapter=adapter,
        param_mgr=param_mgr,
        fitness_calc=fitness_calc,
        algorithm=algorithm,
    )

    history_path = tmp_path / "run" / "opt_history.csv"
    lines = history_path.read_text(encoding="utf-8").strip().splitlines()

    assert len(lines) == 3
    assert algorithm.rejected_candidates == [pytest.approx(0.2)]
    assert algorithm.update_calls == 2
    assert best_params[0] == pytest.approx(0.2)
    assert best_cost == pytest.approx(0.04)
    assert best_result.cost == pytest.approx(0.04)


def test_run_task_promotes_bo_strategy_to_algorithm_aware_fitness(monkeypatch, tmp_path):
    config = {
        "name": "demo_bo_strategy",
        "task_type": "opt",
        "parameters": [
            {"name": "x", "min": -1.0, "max": 1.0, "resolution": 0.01},
        ],
        "target": {
            "freq_band": [54.0, 66.0],
            "s11_threshold": -10,
            "fitness": {"single_objective_strategy": "bo"},
        },
        "algorithm": {"method": "bo"},
        "optimization": {},
        "output": {"save_data": False},
        "simulator": {"hfss": {"setup_name": "Setup1"}},
    }

    captured = {}

    class CapturingFitnessCalculator:
        is_multi_objective = False

        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

        def calculate(self, *args, **kwargs):
            return DummyFitnessCalculator().calculate(*args, **kwargs)

    adapter = DummyOptAdapter()
    monkeypatch.setattr(task_runner, "create_adapter", lambda config, opt_config=None, task_name=None: adapter)
    monkeypatch.setattr(task_runner, "FitnessCalculator", CapturingFitnessCalculator)
    monkeypatch.setattr(task_runner, "create_algorithm", lambda config, param_mgr: SimpleNamespace(is_multi_objective=False))
    monkeypatch.setattr(task_runner, "run_optimization", lambda *args, **kwargs: (None, None, None))
    monkeypatch.setattr(task_runner, "save_config_snapshot", lambda *args, **kwargs: None)

    exit_code = task_runner.run_task(
        config,
        task_output_dir=str(tmp_path / "run"),
        task_work_dir=str(tmp_path / "work"),
    )

    assert exit_code == 0
    assert captured["kwargs"]["fitness_config"]["single_objective_strategy"] == "bo"


def test_run_task_defaults_to_algorithm_aware_fitness_for_new_runs(monkeypatch, tmp_path):
    config = {
        "name": "demo_algorithm_aware_defaults",
        "task_type": "opt",
        "parameters": [
            {"name": "x", "min": -1.0, "max": 1.0, "resolution": 0.01},
        ],
        "target": {
            "freq_band": [54.0, 66.0],
            "s11_threshold": -10,
        },
        "algorithm": {"method": "bo"},
        "optimization": {},
        "output": {"save_data": False},
        "simulator": {"hfss": {"setup_name": "Setup1"}},
    }

    captured = {}

    class CapturingFitnessCalculator:
        is_multi_objective = False

        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

        def calculate(self, *args, **kwargs):
            return DummyFitnessCalculator().calculate(*args, **kwargs)

    adapter = DummyOptAdapter()
    monkeypatch.setattr(task_runner, "create_adapter", lambda config, opt_config=None, task_name=None: adapter)
    monkeypatch.setattr(task_runner, "FitnessCalculator", CapturingFitnessCalculator)
    monkeypatch.setattr(task_runner, "create_algorithm", lambda config, param_mgr: SimpleNamespace(is_multi_objective=False))
    monkeypatch.setattr(task_runner, "run_optimization", lambda *args, **kwargs: (None, None, None))
    monkeypatch.setattr(task_runner, "save_config_snapshot", lambda *args, **kwargs: None)

    exit_code = task_runner.run_task(
        config,
        task_output_dir=str(tmp_path / "run"),
        task_work_dir=str(tmp_path / "work"),
    )

    assert exit_code == 0
    assert captured["kwargs"]["objective_mode"] == "algorithm_aware"
    assert captured["kwargs"]["fitness_config"]["scalarization"] == "weighted_metrics"
    assert captured["kwargs"]["fitness_config"]["adaptive_penalty"] is False


def test_run_task_allows_explicit_legacy_opt_in(monkeypatch, tmp_path):
    config = {
        "name": "demo_explicit_legacy",
        "task_type": "opt",
        "parameters": [
            {"name": "x", "min": -1.0, "max": 1.0, "resolution": 0.01},
        ],
        "target": {
            "freq_band": [54.0, 66.0],
            "s11_threshold": -10,
            "objective_mode": "legacy",
        },
        "algorithm": {"method": "bo"},
        "optimization": {},
        "output": {"save_data": False},
        "simulator": {"hfss": {"setup_name": "Setup1"}},
    }

    captured = {}

    class CapturingFitnessCalculator:
        is_multi_objective = False

        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

        def calculate(self, *args, **kwargs):
            return DummyFitnessCalculator().calculate(*args, **kwargs)

    adapter = DummyOptAdapter()
    monkeypatch.setattr(task_runner, "create_adapter", lambda config, opt_config=None, task_name=None: adapter)
    monkeypatch.setattr(task_runner, "FitnessCalculator", CapturingFitnessCalculator)
    monkeypatch.setattr(task_runner, "create_algorithm", lambda config, param_mgr: SimpleNamespace(is_multi_objective=False))
    monkeypatch.setattr(task_runner, "run_optimization", lambda *args, **kwargs: (None, None, None))
    monkeypatch.setattr(task_runner, "save_config_snapshot", lambda *args, **kwargs: None)

    exit_code = task_runner.run_task(
        config,
        task_output_dir=str(tmp_path / "run"),
        task_work_dir=str(tmp_path / "work"),
    )

    assert exit_code == 0
    assert captured["kwargs"]["objective_mode"] == "legacy"
    assert captured["kwargs"]["fitness_config"] is None


def test_run_task_executes_opt_with_bo(monkeypatch, tmp_path):
    __import__("pytest").importorskip("torch")
    config = {
        "name": "demo_bo",
        "task_type": "opt",
        "parameters": [
            {"name": "x", "min": -1.0, "max": 1.0, "resolution": 0.01},
            {"name": "y", "min": -1.0, "max": 1.0, "resolution": 0.01},
        ],
        "target": {"freq_band": [59.0, 61.0], "s11_threshold": -15},
        "algorithm": {
            "method": "bo",
            "n_initial": 4,
            "max_iterations": 8,
            "max_simulations": 8,
            "early_stop_patience": 8,
        },
        "optimization": {
            "save_best_on_exit": False,
        },
        "output": {
            "save_data": False,
            "plot_fitness_trend": False,
        },
        "simulator": {"hfss": {"setup_name": "Setup1"}},
    }

    adapter = DummyOptAdapter()
    monkeypatch.setattr(task_runner, "create_adapter", lambda config, opt_config=None, task_name=None: adapter)
    monkeypatch.setattr(task_runner, "FitnessCalculator", lambda *args, **kwargs: DummyFitnessCalculator())
    monkeypatch.setattr(task_runner, "save_config_snapshot", lambda *args, **kwargs: None)
    monkeypatch.setattr(task_runner, "_collect_optional_metrics", lambda config, adapter: {})

    exit_code = task_runner.run_task(
        config,
        task_output_dir=str(tmp_path / "run"),
        task_work_dir=str(tmp_path / "work"),
    )

    assert exit_code == 0
    assert adapter.connect_calls == 1
    assert adapter.disconnect_calls == 1
    assert adapter.best_params is not None
    assert adapter.best_fitness < 0.5
    history_header = (tmp_path / "run" / "opt_history.csv").read_text(encoding="utf-8").splitlines()[0]
    assert "bo_phase" in history_header
    assert "bo_pred_mean" in history_header


def test_load_manual_bo_history_rejects_legacy_cost_only_csv(tmp_path):
    from optimizer.algorithms.bo import BOOptimizer
    from optimizer.core.parameter import ParameterManager

    source_dir = tmp_path / "history_run"
    source_dir.mkdir()
    (source_dir / "config.json").write_text(
        json.dumps(
            {
                "task_type": "opt",
                "simulator": {
                    "hfss": {
                        "project_path": "../hfss/demo.aedt",
                        "design_name": "base",
                        "setup_name": "Setup1",
                        "sweep_name": "Sweep1",
                    }
                },
                "target": {
                    "freq_band": [54.0, 66.0],
                    "s11_threshold": -10,
                    "s11_profile": {
                        "interior_threshold": -13,
                        "edge_points": [
                            {"freq": 54.0, "threshold": -10},
                            {"freq": 66.0, "threshold": -10},
                        ],
                        "freq_tolerance": 1e-6,
                    },
                },
                "parameters": [
                    {"name": "x", "unit": "mm"},
                    {"name": "y", "unit": "mm"},
                ],
            }
        ),
        encoding="utf-8",
    )
    (source_dir / "opt_history.csv").write_text(
        "\n".join(
            [
                "sim_id,iter,cost,s11_max,bandwidth,s12_max,target_met,checkpoint,violation_cost,bandwidth_cost,coverage_cost,depth_bonus,geometry_penalty,s12_cost,gain_cost,constraint_penalty,violation_raw,bandwidth_gap_raw,coverage_gap_raw,depth_raw,s12_violation_raw,gain_violation_raw,geometry_raw,constraint_raw,adaptive_violation,adaptive_bandwidth,adaptive_coverage,adaptive_s12,adaptive_gain,constraint_violation,objective_1,objective_2,objective_3,bo_phase,bo_pred_mean,bo_pred_std,bo_abs_error,x,y",
                "1,1,1.250000,-2.00,N/A,N/A,False,True,1.250000,0,0,0,0,0,0,1.250000,1.250000,0,0,0,0,0,0,1.250000,1,1,1,1,1,0,N/A,N/A,N/A,initial,N/A,N/A,N/A,0.10,0.20",
                "2,2,9.990000,-1.00,N/A,N/A,False,True,9.990000,0,0,0,0,0,0,9.990000,9.990000,0,0,0,0,0,0,9.990000,1,1,1,1,1,0,N/A,N/A,N/A,initial,N/A,N/A,N/A,1.50,0.30",
            ]
        ),
        encoding="utf-8",
    )

    config = {
        "task_type": "opt",
        "simulator": {
            "hfss": {
                "project_path": "../hfss/demo.aedt",
                "design_name": "base",
                "setup_name": "Setup1",
                "sweep_name": "Sweep1",
            }
        },
        "target": {
            "freq_band": [54.0, 66.0],
            "s11_threshold": -10,
            "s11_profile": {
                "interior_threshold": -13,
                "edge_points": [
                    {"freq": 54.0, "threshold": -10},
                    {"freq": 66.0, "threshold": -10},
                ],
                "freq_tolerance": 1e-6,
            },
        },
        "parameters": [
            {"name": "x", "min": -1.0, "max": 1.0, "unit": "mm", "resolution": 0.01},
            {"name": "y", "min": -1.0, "max": 1.0, "unit": "mm", "resolution": 0.01},
        ],
        "algorithm": {"method": "bo", "n_initial": 4},
        "history": {"mode": "manual", "sources": [str(source_dir)]},
    }
    param_mgr = ParameterManager(config["parameters"])
    algorithm = BOOptimizer(bounds=param_mgr.get_bounds(), n_initial=4)

    summary = task_runner._load_manual_bo_history(config, algorithm, param_mgr)

    assert summary["loaded"] == 0
    assert summary["rejected_sources"] == 1
    assert "unverified" in summary["rejections"][0]["reason"]
    assert algorithm.history_loaded_count == 0
    assert algorithm.X_train.shape == (0, 2)
    assert config["algorithm"]["history_loaded"] == 0


def test_load_manual_bo_history_rejects_incompatible_target(tmp_path):
    from optimizer.algorithms.bo import BOOptimizer
    from optimizer.core.parameter import ParameterManager

    source_dir = tmp_path / "bad_history_run"
    source_dir.mkdir()
    (source_dir / "config.json").write_text(
        json.dumps(
            {
                "task_type": "opt",
                "simulator": {
                    "hfss": {
                        "project_path": "../hfss/demo.aedt",
                        "design_name": "base",
                        "setup_name": "Setup1",
                        "sweep_name": "Sweep1",
                    }
                },
                "target": {"freq_band": [50.0, 60.0], "s11_threshold": -8},
                "parameters": [
                    {"name": "x", "unit": "mm"},
                ],
            }
        ),
        encoding="utf-8",
    )
    (source_dir / "opt_history.csv").write_text(
        "\n".join(
            [
                "sim_id,iter,cost,s11_max,bandwidth,s12_max,target_met,checkpoint,violation_cost,bandwidth_cost,coverage_cost,depth_bonus,geometry_penalty,s12_cost,gain_cost,constraint_penalty,violation_raw,bandwidth_gap_raw,coverage_gap_raw,depth_raw,s12_violation_raw,gain_violation_raw,geometry_raw,constraint_raw,adaptive_violation,adaptive_bandwidth,adaptive_coverage,adaptive_s12,adaptive_gain,constraint_violation,objective_1,objective_2,objective_3,bo_phase,bo_pred_mean,bo_pred_std,bo_abs_error,x",
                "1,1,1.250000,-2.00,N/A,N/A,False,True,1.250000,0,0,0,0,0,0,1.250000,1.250000,0,0,0,0,0,0,1.250000,1,1,1,1,1,0,N/A,N/A,N/A,initial,N/A,N/A,N/A,0.10",
            ]
        ),
        encoding="utf-8",
    )

    config = {
        "task_type": "opt",
        "simulator": {
            "hfss": {
                "project_path": "../hfss/demo.aedt",
                "design_name": "base",
                "setup_name": "Setup1",
                "sweep_name": "Sweep1",
            }
        },
        "target": {"freq_band": [54.0, 66.0], "s11_threshold": -10},
        "parameters": [
            {"name": "x", "min": -1.0, "max": 1.0, "unit": "mm", "resolution": 0.01},
        ],
        "algorithm": {"method": "bo", "n_initial": 4},
        "history": {"mode": "manual", "sources": [str(source_dir)]},
    }
    param_mgr = ParameterManager(config["parameters"])
    algorithm = BOOptimizer(bounds=param_mgr.get_bounds(), n_initial=4)

    summary = task_runner._load_manual_bo_history(config, algorithm, param_mgr)

    assert summary["loaded"] == 0
    assert summary["rejected_sources"] == 1
    assert algorithm.history_loaded_count == 0
    assert algorithm.X_train.shape == (0, 1)
