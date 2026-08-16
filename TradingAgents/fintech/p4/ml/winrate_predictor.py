"""
winrate_predictor.py - 胜率预测模型

目标：预测未来5日上涨 / 下跌 / 震荡的概率
标签定义（来自 dataset_builder）：
  - up:      close_5d > close × 1.02
  - down:    close_5d < close × 0.98
  - neutral: 其他

信号规则：
  - P_up > 0.65  → LONG
  - P_down > 0.60 → SHORT（可选，本系统仅用 LONG）
  - 其他          → NEUTRAL / WATCH
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, accuracy_score
import joblib
from pathlib import Path
from typing import Optional, Literal


class WinratePredictor:
    """
    胜率预测模型

    使用 GradientBoosting + RandomForest 集成预测未来5日涨跌概率。

    信号含义：
      LONG    → P_up > 0.65，建议做多
      SHORT   → P_down > 0.60（可选）
      WATCH   → 0.50 < P_up <= 0.65，观望
      NEUTRAL → P_up <= 0.50，不操作
    """

    # dataset_builder 输出中可用的特征列（去除元数据列）
    _EXCLUDE_COLS = {"ticker", "ymd", "label_5d", "close_5d", "date"}

    def __init__(self, model_path: Optional[str] = None):
        self.model: Optional[GradientBoostingClassifier] = None
        self.ensemble_models: list = []
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
        从 dataset_builder DataFrame 提取特征矩阵和标签

        Returns:
            (X: np.ndarray, y: np.ndarray, feature_names: list)
        """
        # 去除标签列和非特征列
        drop_cols = list(self._EXCLUDE_COLS & set(df.columns))
        feature_cols = [c for c in df.columns if c not in drop_cols]

        # 只保留数值列
        numeric_df = df[feature_cols].select_dtypes(include=[np.number])
        # 填充 NaN
        numeric_df = numeric_df.fillna(0)

        X = numeric_df.values.astype(np.float32)
        feature_names = list(numeric_df.columns)

        # 标签
        label_map = {"up": "up", "down": "down", "neutral": "neutral"}
        y = df["label_5d"].map(label_map).values

        # 去除 NaN 标签
        valid_mask = ~pd.isna(y)
        X = X[valid_mask]
        y = y[valid_mask]

        return X, y, feature_names

    # ------------------------------------------------------------------
    # 训练
    # ------------------------------------------------------------------

    def train(self, df: pd.DataFrame) -> dict:
        """
        训练胜率预测模型

        Args:
            df: 来自 DatasetBuilder.build_batch() 的 DataFrame，
                包含 label_5d 列

        Returns:
            {'accuracy': float, 'report': str, 'n_samples': int,
             'n_train': int, 'n_val': int}
        """
        X, y, feature_names = self._prepare_features(df)
        self._feature_names = feature_names

        if len(X) < 100:
            raise ValueError(f"训练样本不足（{len(X)}），需要至少 100 条")

        # 80/20 分割
        X_train, X_val, y_train, y_val = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y,
        )

        # 标准化
        X_train_s = self.scaler.fit_transform(X_train)
        X_val_s = self.scaler.transform(X_val)

        # GradientBoosting（主模型）
        self.model = GradientBoostingClassifier(
            n_estimators=200,
            max_depth=5,
            min_samples_leaf=20,
            learning_rate=0.05,
            subsample=0.8,
            random_state=42,
        )
        self.model.fit(X_train_s, y_train)

        # RandomForest（集成备选）
        rf = RandomForestClassifier(
            n_estimators=200,
            max_depth=8,
            min_samples_leaf=10,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        )
        rf.fit(X_train_s, y_train)
        self.ensemble_models = [rf]

        # 评估（主模型）
        y_pred = self.model.predict(X_val_s)
        acc = accuracy_score(y_val, y_pred)
        report = classification_report(y_val, y_pred, digits=4)

        self._is_trained = True

        return {
            "accuracy": round(acc, 4),
            "report": report,
            "n_samples": len(X),
            "n_train": len(X_train),
            "n_val": len(X_val),
        }

    # ------------------------------------------------------------------
    # 推理
    # ------------------------------------------------------------------

    def predict_proba(self, features: dict) -> dict:
        """
        预测未来5日涨跌概率

        Args:
            features: 因子特征字典，键为特征名，值为 float。
                      可来自 calc_all_factors() 输出。

        Returns:
            {
                'P_up': float,       # 上涨概率
                'P_down': float,     # 下跌概率
                'P_neutral': float,  # 震荡概率
                'signal': str,       # 'LONG' / 'WATCH' / 'NEUTRAL'
            }
        """
        if not self._is_trained or self.model is None:
            return self._default_proba()

        X = self._features_dict_to_array(features)
        X_s = self.scaler.transform(X)

        # 主模型概率
        proba = self.model.predict_proba(X_s)[0]
        classes = list(self.model.classes_)

        # 统一输出键名
        result: dict = {"P_up": 0.0, "P_down": 0.0, "P_neutral": 0.0, "signal": "NEUTRAL"}

        for cls, p in zip(classes, proba):
            if cls == "up":
                result["P_up"] = round(float(p), 4)
            elif cls == "down":
                result["P_down"] = round(float(p), 4)
            elif cls == "neutral":
                result["P_neutral"] = round(float(p), 4)

        # 信号判定
        if result["P_up"] > 0.65:
            result["signal"] = "LONG"
        elif result["P_up"] > 0.50:
            result["signal"] = "WATCH"
        else:
            result["signal"] = "NEUTRAL"

        # 集成 RF 概率（简单平均）
        for rf_model in self.ensemble_models:
            rf_proba = rf_model.predict_proba(X_s)[0]
            for cls, p in zip(list(rf_model.classes_), rf_proba):
                if cls == "up":
                    result["P_up"] = round((result["P_up"] + float(p)) / 2, 4)
                elif cls == "down":
                    result["P_down"] = round((result["P_down"] + float(p)) / 2, 4)
                elif cls == "neutral":
                    result["P_neutral"] = round((result["P_neutral"] + float(p)) / 2, 4)

        # 再次判定信号（用集成后概率）
        if result["P_up"] > 0.65:
            result["signal"] = "LONG"
        elif result["P_up"] > 0.50:
            result["signal"] = "WATCH"
        else:
            result["signal"] = "NEUTRAL"

        return result

    def _features_dict_to_array(self, features: dict) -> np.ndarray:
        """将特征字典转换为模型输入数组（按训练时的特征顺序）"""
        if not self._feature_names:
            raise ValueError("模型未训练，无法确定特征顺序")

        arr = np.array([[features.get(fn, 0.0) for fn in self._feature_names]])
        arr = np.nan_to_num(arr, nan=0.0)  # 将NaN替换为0（处理ema200等早期NaN）
        return arr.astype(np.float32)

    @staticmethod
    def _default_proba() -> dict:
        return {"P_up": 0.0, "P_down": 0.0, "P_neutral": 0.0, "signal": "NEUTRAL"}

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
                    "ensemble_models": self.ensemble_models,
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
        self.ensemble_models = data.get("ensemble_models", [])
        self.scaler = data["scaler"]
        self._feature_names = data.get("feature_names", [])
        self._is_trained = data.get("is_trained", self.model is not None)
