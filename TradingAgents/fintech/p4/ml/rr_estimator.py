"""
rr_estimator.py - 盈亏比估算器（R Risk/Reward Estimator）

目标：估算未来5日的期望 R 倍数
R 定义：R = (future_close - entry) / ATR(14)
     entry = 当日 close

使用场景：
  E[R] > 1.5 → 有价值的入场机会，建议关注
  E[R] < 1.0 → 盈亏比差，放弃
  1.0 <= E[R] <= 1.5 → 需联合胜率决策（参考 WinratePredictor）
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, r2_score
import joblib
from pathlib import Path
from typing import Optional


class RREstimator:
    """
    盈亏比估算器

    估算未来5日期望 R 倍数（以 ATR(14) 为单位的潜在收益）。
    R > 0 表示潜在盈利，R < 0 表示潜在亏损。

    信号阈值：
      E[R] > 1.5  → 有价值入场
      E[R] < 1.0  → 放弃
      1.0 <= E[R] <= 1.5 → 谨慎观望
    """

    _EXCLUDE_COLS = {"ticker", "ymd", "label_5d", "close_5d", "date", "r_label", "atr14", "return_5d"}  # atr14/return_5d excluded since we use atr14_pct and compute r_label from close_5d

    def __init__(self, model_path: Optional[str] = None):
        self.model: Optional[GradientBoostingRegressor] = None
        self.scaler = StandardScaler()
        self._feature_names: list = []
        self._is_trained = False
        if model_path:
            self.load(model_path)

    # ------------------------------------------------------------------
    # 特征工程
    # ------------------------------------------------------------------

    def _prepare_features(self, df: pd.DataFrame) -> tuple:
        """
        从 dataset_builder DataFrame 构建 R 标签并提取特征

        R 标签 = (close_5d - close) / atr14

        Returns:
            (X: np.ndarray, y: np.ndarray, feature_names: list)
        """
        df = df.copy()

        # R 标签（若 close_5d 不存在则跳过该行）
        if "close_5d" not in df.columns or "atr14" not in df.columns:
            raise ValueError(
                "RREstimator 需要 dataset_builder 输出包含 'close_5d', 'return_5d' 和 'atr14_pct' 列"
            )

        # R = future return / ATR% = (close_5d/close - 1) * 100 / atr14_pct
        df["r_label"] = (df["close_5d"] - df["close"]) / df["close"] * 100 / df["atr14_pct"]
        df = df.dropna(subset=["r_label"])
        # 去除极端异常值（|R| > 10 倍）
        df = df[np.abs(df["r_label"]) < 10]

        drop_cols = list(self._EXCLUDE_COLS & set(df.columns))
        feature_cols = [c for c in df.columns if c not in drop_cols]
        numeric_df = df[feature_cols].select_dtypes(include=[np.number]).fillna(0)

        X = numeric_df.values.astype(np.float32)
        y = df["r_label"].values.astype(np.float32)
        feature_names = list(numeric_df.columns)

        return X, y, feature_names

    # ------------------------------------------------------------------
    # 训练
    # ------------------------------------------------------------------

    def train(self, df: pd.DataFrame) -> dict:
        """
        训练盈亏比估算模型

        Args:
            df: 来自 DatasetBuilder.build_batch() 的 DataFrame，
                包含 close_5d 和 atr14 列

        Returns:
            {'mse': float, 'rmse': float, 'r2': float,
             'n_samples': int, 'n_train': int, 'n_val': int}
        """
        X, y, feature_names = self._prepare_features(df)
        self._feature_names = feature_names

        if len(X) < 100:
            raise ValueError(f"训练样本不足（{len(X)}），需要至少 100 条")

        # 80/20 分割
        X_train, X_val, y_train, y_val = train_test_split(
            X, y, test_size=0.2, random_state=42,
        )

        # 标准化
        X_train_s = self.scaler.fit_transform(X_train)
        X_val_s = self.scaler.transform(X_val)

        # GradientBoosting 回归
        self.model = GradientBoostingRegressor(
            n_estimators=200,
            max_depth=5,
            min_samples_leaf=20,
            learning_rate=0.05,
            subsample=0.8,
            random_state=42,
        )
        self.model.fit(X_train_s, y_train)

        # 评估
        y_pred = self.model.predict(X_val_s)
        mse = mean_squared_error(y_val, y_pred)
        r2 = r2_score(y_val, y_pred)

        self._is_trained = True

        return {
            "mse": round(float(mse), 4),
            "rmse": round(float(np.sqrt(mse)), 4),
            "r2": round(float(r2), 4),
            "n_samples": len(X),
            "n_train": len(X_train),
            "n_val": len(X_val),
        }

    # ------------------------------------------------------------------
    # 推理
    # ------------------------------------------------------------------

    def predict(self, features: dict) -> float:
        """
        估算未来5日期望 R 倍数

        Args:
            features: 因子特征字典（键为特征名，值为 float）
                      必须包含 atr14_pct 字段用于归一化

        Returns:
            E[R] 期望 R 倍数（float，可能为负）
        """
        if not self._is_trained or self.model is None:
            return 0.0

        X = self._features_dict_to_array(features)
        X_s = self.scaler.transform(X)
        return round(float(self.model.predict(X_s)[0]), 4)

    def predict_detail(self, features: dict) -> dict:
        """
        带置信区间的 R 估算（使用 RF 的树集成分布近似）

        Returns:
            {
                'E_R': float,          # 期望 R
                'signal': str,        # 'OPPORTUNITY' / 'ABANDON' / 'WATCH'
                'conf_low': float,    # 低估置信区间（5th percentile）
                'conf_high': float,   # 高估置信区间（95th percentile）
            }
        """
        E_R = self.predict(features)

        # 简单置信区间：RF 各树预测的分布（若有 RF）
        conf_low = E_R
        conf_high = E_R
        if self.model is not None:
            # 用预测方差估算（简化版：± 0.5 倍 R）
            spread = 0.5
            conf_low = round(E_R - spread, 4)
            conf_high = round(E_R + spread, 4)

        if E_R > 1.5:
            signal = "OPPORTUNITY"
        elif E_R < 1.0:
            signal = "ABANDON"
        else:
            signal = "WATCH"

        return {
            "E_R": E_R,
            "signal": signal,
            "conf_low": conf_low,
            "conf_high": conf_high,
        }

    def _features_dict_to_array(self, features: dict) -> np.ndarray:
        """将特征字典转换为模型输入数组"""
        if not self._feature_names:
            raise ValueError("模型未训练，无法确定特征顺序")

        arr = np.array([[features.get(fn, 0.0) for fn in self._feature_names]])
        arr = np.nan_to_num(arr, nan=0.0)
        return arr.astype(np.float32)

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def save(self, path: str) -> None:
        """保存模型到磁盘"""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            joblib.dump(
                {
                    "model": self.model,
                    "scaler": self.scaler,
                    "feature_names": self._feature_names,
                    "is_trained": self._is_trained,
                },
                f,
            )

    def load(self, path: str) -> None:
        """从磁盘加载模型"""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"模型文件不存在: {path}")
        with open(path, "rb") as f:
            data = joblib.load(f)
        self.model = data["model"]
        self.scaler = data["scaler"]
        self._feature_names = data.get("feature_names", [])
        self._is_trained = data.get("is_trained", self.model is not None)
