"""
CSV数据适配器
从CSV文件读取仿真结果，用于已有数据的分析
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from typing import Tuple, Optional
from adapters.base import SimulatorAdapter
from core.reader import ResultReader


class CSVAdapter(SimulatorAdapter):
    """CSV适配器，用于从CSV文件读取仿真结果"""

    def __init__(self, config: dict):
        super().__init__(config)
        self.data_path = config.get('data_path', '')
        self.columns = config.get('columns', {})
        self.current_params = None
        self.freqs = None
        self.s11 = None
        self.s21 = None

    def connect(self) -> bool:
        """从CSV文件读取数据"""
        if not self.data_path or not os.path.exists(self.data_path):
            print(f"CSV文件不存在: {self.data_path}")
            return False

        try:
            reader = ResultReader()
            self.freqs, self.s11, self.s21 = reader.read_csv(self.data_path)
            self._is_connected = True
            print(f"已加载CSV数据: {self.data_path}")
            return True
        except Exception as e:
            print(f"读取CSV失败: {e}")
            return False

    def disconnect(self):
        """断开连接"""
        self.freqs = None
        self.s11 = None
        self.s21 = None
        self._is_connected = False

    def set_parameters(self, params: np.ndarray) -> bool:
        """设置参数（CSV适配器仅记录，不实际设置）"""
        self.current_params = params.copy()
        return True

    def simulate(self) -> Tuple[np.ndarray, np.ndarray, Optional[np.ndarray]]:
        """返回已加载的数据"""
        if not self._is_connected:
            return None, None, None
        return self.freqs, self.s11, self.s21

    def get_params(self) -> np.ndarray:
        """获取当前参数"""
        return self.current_params