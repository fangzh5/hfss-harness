import json
import math
from types import SimpleNamespace

import pytest

from optimizer.task_runner import _save_pareto_front
from optimizer.dashboard.state_bridge import build_dashboard_snapshot


def front():
    return [{"params":[1.,2.],"objectives":[-10.,-15.],"constraint_violation":0.,
             "rank":0,"crowding_distance":math.inf,"source_sim_id":3}]


def strict(text):
    return json.loads(text,parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def test_boundary_infinite_crowding_is_explicit_valid_json_and_does_not_mutate_algorithm(tmp_path):
    raw = front()
    algorithm = SimpleNamespace(is_multi_objective=True,get_pareto_front=lambda:raw)
    path = _save_pareto_front(str(tmp_path),algorithm,["a","b"])
    with open(path) as stream: saved = strict(stream.read())
    assert saved[0]["crowding_distance"] is None and saved[0]["crowding_unbounded"]
    assert saved[0]["params_map"] == {"a":1.,"b":2.}
    assert math.isinf(raw[0]["crowding_distance"])


@pytest.mark.parametrize("distance", [math.nan,-math.inf])
def test_invalid_crowding_is_rejected_before_creating_export(tmp_path,distance):
    raw=front();raw[0]["crowding_distance"]=distance
    with pytest.raises(ValueError):
        _save_pareto_front(str(tmp_path),SimpleNamespace(is_multi_objective=True,get_pareto_front=lambda:raw),["a","b"])
    assert not list(tmp_path.iterdir())


def test_nonfinite_objective_cannot_hide_behind_valid_infinite_crowding(tmp_path):
    raw=front();raw[0]["objectives"][0]=math.nan
    with pytest.raises(ValueError):
        _save_pareto_front(str(tmp_path),SimpleNamespace(is_multi_objective=True,get_pareto_front=lambda:raw),["a","b"])
    assert not list(tmp_path.iterdir())


def test_multiobjective_dashboard_snapshot_is_strict_json():
    payload=build_dashboard_snapshot(config={"target":{"multi_objective":{"enabled":True}},"parameters":[]},pareto_front=front())
    decoded=strict(json.dumps(payload,allow_nan=False))
    assert decoded["paretoFront"][0]["crowding_unbounded"] is True
