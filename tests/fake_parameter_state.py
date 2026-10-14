"""Small offline adapter fixture implementing the full baseline contract."""

import numpy as np


class FakeParameterState:
    def capture_current_parameter_state(self, names=None):
        keys = list(self.config.get("param_names", ["x"]))
        values = self.current_params if self.current_params is not None else np.zeros(len(keys))
        state = dict(zip(keys, np.asarray(values).tolist()))
        return state if names is None else {name: state[name] for name in names}

    def restore_parameter_state(self, state):
        keys = list(self.config.get("param_names", ["x"]))
        self.current_params = np.array([state[name] for name in keys], dtype=float)
        return True
