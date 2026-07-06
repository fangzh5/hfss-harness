"""
粒子群优化算法 (PSO)
通过粒子的位置和速度迭代搜索最优解
"""

import numpy as np
from typing import List
from .base import OptimizationAlgorithm


class PSOOptimizer(OptimizationAlgorithm):
    """
    粒子群优化器

    参数说明：
    - n_particles: 粒子数量，推荐20~50，维度高时取较大值
    - w: 惯性权重，推荐0.4~0.9，较大值利于全局搜索，较小的值利于局部精细搜索
    - c1: 个体学习因子，推荐1.5~2.0，控制粒子向自身最优学习的倾向
    - c2: 群体学习因子，推荐1.5~2.0，较大值加快收敛，但可能陷入局部最优
    - max_velocity: 最大速度，推荐step的1~2倍，防止步长过大跳过最优解
    """

    def __init__(
        self,
        bounds: List[tuple],
        n_particles: int = 30,
        w: float = 0.7,
        c1: float = 1.5,
        c2: float = 1.5,
        max_velocity: float = 0.5,
        step_size: np.ndarray = None
    ):
        super().__init__(bounds, n_particles)
        self.w = w
        self.c1 = c1
        self.c2 = c2
        self.max_velocity = max_velocity
        self.step_size = step_size

        self.n_dims = len(bounds)
        self.positions = self._init_positions()
        self.velocities = self._init_velocities()
        self.personal_best_positions = self.positions.copy()
        self.personal_best_costs = np.full(n_particles, float('inf'))
        self.global_best_position = None
        self.global_best_cost = float('inf')

    def _init_positions(self) -> np.ndarray:
        """初始化粒子位置"""
        positions = np.zeros((self.n_particles, self.n_dims))
        for i, (low, high) in enumerate(self.bounds):
            positions[:, i] = np.random.uniform(low, high, self.n_particles)
        return positions

    def _init_velocities(self) -> np.ndarray:
        """初始化粒子速度"""
        max_vel = self.max_velocity
        if self.step_size is not None:
            max_vel = self.step_size * 2
        return np.random.uniform(-max_vel, max_vel, (self.n_particles, self.n_dims))

    def suggest(self) -> np.ndarray:
        """返回当前最优位置作为建议"""
        if self.global_best_position is None:
            return self.positions[0]
        return self.global_best_position.copy()

    def suggest_population(self) -> np.ndarray:
        """返回整个粒子群作为候选"""
        return self.positions.copy()

    def update(self, fitness_results: List):
        """更新粒子群状态"""
        for result in fitness_results:
            if not hasattr(result, 'cost'):
                continue
            cost = result.cost
            idx = getattr(result, 'particle_idx', 0)

            if idx >= self.n_particles:
                continue

            if cost < self.personal_best_costs[idx]:
                self.personal_best_costs[idx] = cost
                self.personal_best_positions[idx] = self.positions[idx].copy()

            if cost < self.global_best_cost:
                self.global_best_cost = cost
                self.global_best_position = self.positions[idx].copy()

        self._update_velocities()
        self._update_positions()

    def _update_velocities(self):
        """更新粒子速度"""
        r1, r2 = np.random.random((2, self.n_dims))

        cognitive = self.c1 * r1 * (self.personal_best_positions - self.positions)
        social = self.c2 * r2 * (self.global_best_position - self.positions) if self.global_best_position is not None else 0

        self.velocities = self.w * self.velocities + cognitive + social

        max_vel = self.max_velocity
        if self.step_size is not None:
            max_vel = self.step_size * 2

        for i in range(self.n_dims):
            self.velocities[:, i] = np.clip(self.velocities[:, i], -max_vel[i], max_vel[i])

    def _update_positions(self):
        """更新粒子位置"""
        self.positions += self.velocities

        for i, (low, high) in enumerate(self.bounds):
            self.positions[:, i] = np.clip(self.positions[:, i], low, high)

    def get_best(self) -> np.ndarray:
        """获取最优位置"""
        if self.global_best_position is None:
            return self.positions[0]
        return self.global_best_position.copy()

    @property
    def name(self) -> str:
        return "PSO"