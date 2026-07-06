"""
代理模型辅助优化算法
使用高斯过程(GPR)作为代理模型减少真实仿真次数
"""

import numpy as np
from typing import List, Optional
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, WhiteKernel
from .base import OptimizationAlgorithm


class SurrogateOptimizer(OptimizationAlgorithm):
    """
    代理模型辅助优化器

    使用高斯过程回归(GPR)作为代理模型，先用少量采样点训练模型，
    然后在代理模型上快速预测筛选候选解，减少真实仿真次数。

    参数说明：
    - base_algorithm: 基础算法类型，'pso' 或 'de'
    - n_initial: 初始采样点数，推荐20~50，至少为参数维度的3~5倍
    - n_candidates: 每轮候选解数量，推荐10~30，影响探索与利用的平衡
    - acquisition: 获取函数类型，'ei' (期望提升) 或 'ucb' (置信上界)
    - alpha: GPR噪声假设，推荐0.01~0.1，较大值增强泛化能力

    适用场景：
    - 仿真耗时长(>30s/次)
    - 参数维度 <= 20
    - 目标空间连续可微
    """

    def __init__(
        self,
        bounds: List[tuple],
        base_algorithm: str = 'de',
        n_initial: int = 30,
        n_candidates: int = 20,
        acquisition: str = 'ei',
        alpha: float = 0.05,
        step_size: np.ndarray = None
    ):
        super().__init__(bounds, n_candidates)
        self.base_algorithm = base_algorithm
        self.n_initial = n_initial
        self.n_candidates = n_candidates
        self.acquisition = acquisition
        self.alpha = alpha
        self.step_size = step_size

        self.n_dims = len(bounds)
        self.X_train = np.zeros((0, self.n_dims))
        self.y_train = np.zeros(0)
        self.gpr = self._init_gpr()
        self.is_trained = False
        self.sampling_count = 0

        from .de import DEOptimizer
        from .pso import PSOOptimizer

        if base_algorithm == 'de':
            self.base_opt = DEOptimizer(bounds, pop_size=n_candidates, step_size=step_size)
        else:
            self.base_opt = PSOOptimizer(bounds, n_particles=n_candidates, step_size=step_size)

    def _init_gpr(self) -> GaussianProcessRegressor:
        """初始化高斯过程回归模型"""
        kernel = RBF(length_scale=1.0, length_scale_bounds=(1e-2, 1e3)) + WhiteKernel(noise_level=self.alpha)
        return GaussianProcessRegressor(kernel=kernel, alpha=self.alpha, n_restarts_optimizer=5)

    def add_training_data(self, X: np.ndarray, y: np.ndarray):
        """添加训练数据"""
        if len(X) == 0:
            return
        self.X_train = np.vstack([self.X_train, X]) if len(self.X_train) > 0 else X
        self.y_train = np.concatenate([self.y_train, y]) if len(self.y_train) > 0 else y

    def train_surrogate(self):
        """训练代理模型"""
        if len(self.X_train) < 2:
            return

        try:
            self.gpr.fit(self.X_train, self.y_train)
            self.is_trained = True
        except Exception:
            self.is_trained = False

    def predict(self, X: np.ndarray) -> tuple:
        """使用代理模型预测"""
        if not self.is_trained:
            return np.full(len(X), float('inf')), np.full(len(X), 0.0)

        try:
            y_pred, y_std = self.gpr.predict(X, return_std=True)
            return y_pred, y_std
        except Exception:
            return np.full(len(X), float('inf')), np.full(len(X), 0.0)

    def expected_improvement(self, X: np.ndarray) -> np.ndarray:
        """计算期望提升获取函数"""
        y_pred, y_std = self.predict(X)

        if len(self.y_train) == 0:
            return np.zeros(len(X))

        y_min = np.min(self.y_train)
        gamma = (y_min - y_pred) / (y_std + 1e-10)
        ei = (y_min - y_pred) * self._norm_cdf(gamma) + y_std * self._norm_pdf(gamma)

        return ei * (y_std > 1e-6)

    def upper_confidence_bound(self, X: np.ndarray, kappa: float = 2.0) -> np.ndarray:
        """计算置信上界获取函数"""
        y_pred, y_std = self.predict(X)
        return y_pred + kappa * y_std

    def _norm_cdf(self, x: np.ndarray) -> np.ndarray:
        """标准正态分布CDF"""
        return 0.5 * (1.0 + np.erf(x / np.sqrt(2)))

    def _norm_pdf(self, x: np.ndarray) -> np.ndarray:
        """标准正态分布PDF"""
        return np.exp(-0.5 * x**2) / np.sqrt(2 * np.pi)

    def suggest(self) -> np.ndarray:
        """生成候选参数建议"""
        if self.sampling_count < self.n_initial:
            self.sampling_count += 1
            return self.base_opt.suggest()

        if not self.is_trained:
            return self.base_opt.suggest()

        candidates = self.base_opt.suggest_population()

        if self.acquisition == 'ei':
            scores = self.expected_improvement(candidates)
        else:
            scores = self.upper_confidence_bound(candidates)

        best_idx = np.argmax(scores)
        return candidates[best_idx].copy()

    def update(self, fitness_results: List):
        """更新代理模型和基础算法"""
        X_new = []
        y_new = []

        for result in fitness_results:
            if hasattr(result, 'params') and hasattr(result, 'cost'):
                X_new.append(result.params)
                y_new.append(result.cost)

        if X_new:
            self.add_training_data(np.array(X_new), np.array(y_new))
            self.train_surrogate()

        self.base_opt.update(fitness_results)

        if self.base_opt.best_params is not None:
            self.best_params = self.base_opt.best_params.copy()
            self.best_cost = self.base_opt.best_cost

    def get_best(self) -> np.ndarray:
        """获取最优位置"""
        if self.best_params is not None:
            return self.best_params.copy()
        return self.base_opt.get_best()

    @property
    def name(self) -> str:
        return f"Surrogate({self.base_algorithm})"