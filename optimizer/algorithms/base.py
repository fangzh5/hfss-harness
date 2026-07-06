"""
优化算法基类
定义所有优化算法的公共接口
"""

from abc import ABC, abstractmethod
import numpy as np
from typing import List


class OptimizationAlgorithm(ABC):
    """优化算法基类"""

    def __init__(self, bounds: List[tuple], n_particles: int = 20):
        self.bounds = bounds
        self.n_particles = n_particles
        self.best_params = None
        self.best_cost = float('inf')
        self.history = []

    @abstractmethod
    def suggest(self) -> np.ndarray:
        """生成候选参数建议"""
        pass

    @abstractmethod
    def update(self, fitness_history: List):
        """根据适应度历史更新算法状态"""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """算法名称"""
        pass

    def update_best(self, params: np.ndarray, cost: float):
        """更新最优解"""
        if cost < self.best_cost:
            self.best_cost = cost
            self.best_params = params.copy()
            return True
        return False

    @property
    def is_multi_objective(self) -> bool:
        """Whether the algorithm consumes Pareto-style objective vectors."""
        return False
