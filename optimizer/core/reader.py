"""
结果读取模块
支持从CSV、JSON或直接数组读取仿真结果
"""

import csv
import json
import numpy as np
from typing import Tuple, Optional
import re

try:
    from ..results import frequency_to_ghz, TraceData
except ImportError:  # pragma: no cover
    from results import frequency_to_ghz, TraceData


class ResultReader:
    """结果读取器"""

    @staticmethod
    def read_csv(filepath: str, *, frequency_unit: str = "GHz", columns=None) -> Tuple[np.ndarray, np.ndarray, Optional[np.ndarray]]:
        """从CSV文件读取结果"""
        freqs = []
        s11 = []
        s21 = []

        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            columns = columns or {}
            freq_key = columns.get("freq") or next((key for key in headers if re.fullmatch(
                r"freq(?:\s*\[(?:Hz|kHz|MHz|GHz|THz)\])?", key, re.I)), None)
            s11_key = columns.get("s11") or next((key for key in headers if key.lower() == "s11"), None)
            s21_key = columns.get("s12", columns.get("s21")) or next((key for key in headers if key.lower() in {"s12", "s21"}), None)
            if freq_key not in headers or s11_key not in headers:
                raise ValueError("CSV requires explicit frequency and S11 columns")
            header_unit = re.search(r"\[(\w+)\]", freq_key)
            if header_unit:
                frequency_unit = header_unit[1]
            for row in reader:
                freqs.append(float(row[freq_key]))
                s11.append(float(row[s11_key]))
                if s21_key is not None:
                    s21.append(float(row[s21_key]))

        freqs = np.array(freqs)
        s11 = np.array(s11)
        s21 = np.array(s21) if s21 else None

        return ResultReader.read_arrays(frequency_to_ghz(freqs, frequency_unit), s11, s21)

    @staticmethod
    def read_json(filepath: str) -> Tuple[np.ndarray, np.ndarray, Optional[np.ndarray]]:
        """从JSON文件读取结果"""
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        freqs = np.array(data.get('freq_ghz', data.get('freq', [])))
        s11 = np.array(data.get('s11_db', data.get('s11', [])))
        s21_data = data.get('s21_db', data.get('s21'))
        s21 = np.array(s21_data) if s21_data else None

        unit = "GHz" if "freq_ghz" in data else data.get("frequency_unit", "GHz")
        return ResultReader.read_arrays(frequency_to_ghz(freqs, unit), s11, s21)

    @staticmethod
    def read_arrays(freqs: np.ndarray, s11: np.ndarray,
                   gain: Optional[np.ndarray] = None) -> Tuple[np.ndarray, np.ndarray, Optional[np.ndarray]]:
        """直接读取数组"""
        trace = TraceData("S11", freqs, s11)
        if gain is not None:
            TraceData("isolation", freqs, gain)
        return trace.frequencies_ghz, trace.values, np.asarray(gain, dtype=float) if gain is not None else None
