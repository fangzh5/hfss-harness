"""
结果读取模块
支持从CSV、JSON或直接数组读取仿真结果
"""

import csv
import json
import numpy as np
from typing import Tuple, Optional


class ResultReader:
    """结果读取器"""

    @staticmethod
    def read_csv(filepath: str) -> Tuple[np.ndarray, np.ndarray, Optional[np.ndarray]]:
        """从CSV文件读取结果"""
        freqs = []
        s11 = []
        s21 = []

        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                freqs.append(float(row.get('Freq', row.get('freq', 0))))
                s11.append(float(row.get('S11', row.get('s11', 0))))
                s21_val = row.get('S21', row.get('s21'))
                if s21_val:
                    s21.append(float(s21_val))

        freqs = np.array(freqs)
        s11 = np.array(s11)
        s21 = np.array(s21) if s21 else None

        return freqs, s11, s21

    @staticmethod
    def read_json(filepath: str) -> Tuple[np.ndarray, np.ndarray, Optional[np.ndarray]]:
        """从JSON文件读取结果"""
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        freqs = np.array(data.get('freq_ghz', data.get('freq', [])))
        s11 = np.array(data.get('s11_db', data.get('s11', [])))
        s21_data = data.get('s21_db', data.get('s21'))
        s21 = np.array(s21_data) if s21_data else None

        return freqs, s11, s21

    @staticmethod
    def read_arrays(freqs: np.ndarray, s11: np.ndarray,
                   gain: Optional[np.ndarray] = None) -> Tuple[np.ndarray, np.ndarray, Optional[np.ndarray]]:
        """直接读取数组"""
        return freqs, s11, gain