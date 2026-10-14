"""
仿真器适配器基类
定义所有仿真器适配器的公共接口
"""

from abc import ABC, abstractmethod
import numpy as np
from typing import Tuple, Optional


class SimulatorAdapter(ABC):
    """仿真器适配器基类"""

    def __init__(self, config: dict):
        self.config = config
        self._is_connected = False

    @abstractmethod
    def connect(self) -> bool:
        """连接到仿真器"""
        pass

    @abstractmethod
    def disconnect(self):
        """断开仿真器连接"""
        pass

    @abstractmethod
    def set_parameters(self, params: np.ndarray) -> bool:
        """设置仿真参数"""
        pass

    @abstractmethod
    def simulate(self) -> Tuple[np.ndarray, np.ndarray, Optional[np.ndarray]]:
        """执行仿真并返回结果"""
        pass

    @property
    def is_connected(self) -> bool:
        """是否已连接"""
        return self._is_connected
