"""
model_manager.py - ML 模型统一管理 + 推理入口

整合 MarketClassifier / WinratePredictor / RREstimator
提供批量训练、加载、推理接口。

目录结构：
  models/
    market_clf.pkl      # 市场分类器
    winrate_model.pkl   # 胜率预测器
    rr_model.pkl        # 盈亏比估算器

用法：
    mm = ModelManager('models/')
    mm.train_all(df)              # 批量训练
    mm.load_all()                 # 加载已有模型
    result = mm.infer(features)    # 综合推理
"""

import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any

from .market_classifier import MarketClassifier
from .winrate_predictor import WinratePredictor
from .rr_estimator import RREstimator

logger = logging.getLogger(__name__)


class ModelManager:
    """
    统一管理所有 ML 模型

    提供：
      - train_all()    批量训练
      - load_all()     加载已有模型（不存在则跳过）
      - save_all()     保存所有模型
      - infer()        综合推理入口
    """

    def __init__(self, model_dir: str = "models/"):
        base = Path(__file__).parent.parent.parent
        if not Path(model_dir).is_absolute():
            self.model_dir = base / model_dir
        else:
            self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)

        self.market_clf = MarketClassifier()
        self.winrate_model = WinratePredictor()
        self.rr_model = RREstimator()

        self._loaded = {"market_clf": False, "winrate": False, "rr": False}

    # ------------------------------------------------------------------
    # 批量训练
    # ------------------------------------------------------------------

    def train_all(self, df, spy_df: Optional[Any] = None) -> Dict[str, Dict]:
        """
        批量训练所有模型

        Args:
            df: DatasetBuilder.build_batch() 的 DataFrame
            spy_df: 可选，SPY 专用 DataFrame（用于 MarketClassifier 单独训练）
                   若不提供则从 df 中提取 SPY 数据

        Returns:
            {
                'market_clf': {...训练结果},
                'winrate': {...训练结果},
                'rr': {...训练结果},
            }
        """
        results = {}

        # 1. 市场分类器
        # 若提供了独立的 spy_df，用它训练；否则从 df 中取 SPY 行
        if spy_df is not None:
            clf_df = spy_df
        else:
            if "ticker" in df.columns:
                clf_df = df[df["ticker"] == "SPY"].copy() if "SPY" in df["ticker"].values else df
            else:
                clf_df = df

        try:
            results["market_clf"] = self.market_clf.train(clf_df)
            self._loaded["market_clf"] = True
            logger.info(f"[ModelManager] MarketClassifier 训练完成: {results['market_clf']}")
        except Exception as e:
            logger.warning(f"[ModelManager] MarketClassifier 训练失败: {e}")
            results["market_clf"] = {"error": str(e)}

        # 2. 胜率预测器
        try:
            results["winrate"] = self.winrate_model.train(df)
            self._loaded["winrate"] = True
            logger.info(f"[ModelManager] WinratePredictor 训练完成: {results['winrate']}")
        except Exception as e:
            logger.warning(f"[ModelManager] WinratePredictor 训练失败: {e}")
            results["winrate"] = {"error": str(e)}

        # 3. 盈亏比估算器
        try:
            results["rr"] = self.rr_model.train(df)
            self._loaded["rr"] = True
            logger.info(f"[ModelManager] RREstimator 训练完成: {results['rr']}")
        except Exception as e:
            logger.warning(f"[ModelManager] RREstimator 训练失败: {e}")
            results["rr"] = {"error": str(e)}

        return results

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def save_all(self) -> None:
        """保存所有已加载的模型到磁盘"""
        paths = {
            "market_clf": self.model_dir / "market_clf.pkl",
            "winrate": self.model_dir / "winrate_model.pkl",
            "rr": self.model_dir / "rr_model.pkl",
        }

        if self._loaded.get("market_clf"):
            self.market_clf.save(str(paths["market_clf"]))
            logger.info(f"[ModelManager] 已保存 MarketClassifier → {paths['market_clf']}")

        if self._loaded.get("winrate"):
            self.winrate_model.save(str(paths["winrate"]))
            logger.info(f"[ModelManager] 已保存 WinratePredictor → {paths['winrate']}")

        if self._loaded.get("rr"):
            self.rr_model.save(str(paths["rr"]))
            logger.info(f"[ModelManager] 已保存 RREstimator → {paths['rr']}")

    def load_all(self) -> Dict[str, bool]:
        """
        尝试加载所有已训练的模型（不存在则跳过）

        Returns:
            {'market_clf': bool, 'winrate': bool, 'rr': bool}
            指示各模型是否成功加载
        """
        paths = {
            "market_clf": self.model_dir / "market_clf.pkl",
            "winrate": self.model_dir / "winrate_model.pkl",
            "rr": self.model_dir / "rr_model.pkl",
        }

        for key, path in paths.items():
            if path.exists():
                try:
                    if key == "market_clf":
                        self.market_clf.load(str(path))
                        self._loaded[key] = True
                    elif key == "winrate":
                        self.winrate_model.load(str(path))
                        self._loaded[key] = True
                    elif key == "rr":
                        self.rr_model.load(str(path))
                        self._loaded[key] = True
                    logger.info(f"[ModelManager] 已加载 {key} ← {path}")
                except Exception as e:
                    logger.warning(f"[ModelManager] 加载 {key} 失败: {e}")
                    self._loaded[key] = False
            else:
                logger.info(f"[ModelManager] 模型文件不存在，跳过: {path}")
                self._loaded[key] = False

        return self._loaded.copy()

    # ------------------------------------------------------------------
    # 综合推理
    # ------------------------------------------------------------------

    def infer(self, features: dict) -> dict:
        """
        综合推理入口

        输入：完整因子特征字典（可来自 calc_all_factors 或各因子文件输出）
        结构示例：
        {
            # 市场特征（用于 MarketClassifier）
            'spy_close': float, 'spy_ema20': float, 'spy_ema50': float,
            'spy_ema200': float, 'spy_adx': float, 'vix': float,
            'qqq_spy_ratio': float,
            # 因子特征（用于 WinratePredictor + RREstimator）
            'return_5d': float, 'rsi14': float, 'atr14': float,
            'mom5': float, 'bb_pos': float, ...（所有数值因子）
        }

        输出：
        {
            'market_state': str,   # 'Trend'/'Neutral'/'Panic'
            'market_proba': dict, # 各类别概率
            'P_up': float,         # 上涨概率
            'P_down': float,      # 下跌概率
            'P_neutral': float,   # 震荡概率
            'signal': str,         # 'LONG'/'WATCH'/'NEUTRAL'
            'E_R': float,         # 期望 R 倍数
            'rr_signal': str,     # 'OPPORTUNITY'/'WATCH'/'ABANDON'
            'conf_low': float,    # R 置信下限
            'conf_high': float,   # R 置信上限
            'action': str,         # 综合建议：'CONSIDER_LONG'/'WATCH'/'ABANDON'
        }
        """
        # 1. 市场状态
        market_feats = {
            "spy_close": features.get("spy_close", features.get("close", 0)),
            "spy_ema20": features.get("spy_ema20", 0),
            "spy_ema50": features.get("spy_ema50", 0),
            "spy_ema200": features.get("spy_ema200", 0),
            "spy_adx": features.get("spy_adx", 20.0),
            "vix": features.get("vix", 20.0),
            "qqq_spy_ratio": features.get("qqq_spy_ratio", 1.0),
        }
        market_state = self.market_clf.predict(market_feats)
        market_proba = self.market_clf.predict_proba(market_feats)

        # 2. 胜率预测
        winrate_proba = self.winrate_model.predict_proba(features)

        # 3. 盈亏比估算
        rr_detail = self.rr_model.predict_detail(features)

        # 4. 综合 action 判定
        action = self._decide_action(
            market_state=market_state,
            win_signal=winrate_proba["signal"],
            rr_signal=rr_detail["signal"],
            P_up=winrate_proba["P_up"],
            E_R=rr_detail["E_R"],
        )

        return {
            # 市场状态
            "market_state": market_state,
            "market_proba": market_proba,
            # 胜率
            "P_up": winrate_proba["P_up"],
            "P_down": winrate_proba["P_down"],
            "P_neutral": winrate_proba["P_neutral"],
            "signal": winrate_proba["signal"],
            # 盈亏比
            "E_R": rr_detail["E_R"],
            "rr_signal": rr_detail["signal"],
            "conf_low": rr_detail["conf_low"],
            "conf_high": rr_detail["conf_high"],
            # 综合操作建议
            "action": action,
        }

    @staticmethod
    def _decide_action(
        market_state: str,
        win_signal: str,
        rr_signal: str,
        P_up: float,
        E_R: float,
    ) -> str:
        """
        综合决策逻辑

        决策树：
        1. 市场状态 Panic → ABANDON（立即离场，不入场）
        2. 市场状态 Trend + LONG信号 + OPPORTUNITY → CONSIDER_LONG
        3. 市场状态 Trend/Neutral + WATCH + OPPORTUNITY → WATCH
        4. ABANDON（任意模型给出 ABANDON）→ ABANDON
        5. 其他 → WATCH
        """
        # 恐慌市场，任何做多都是危险的
        if market_state == "Panic":
            return "ABANDON"

        # 放弃信号
        if rr_signal == "ABANDON":
            return "ABANDON"

        # 三重确认：Trend 市场 + LONG 信号 + 盈亏比机会
        if market_state == "Trend" and win_signal == "LONG" and rr_signal == "OPPORTUNITY":
            return "CONSIDER_LONG"

        # 观望
        return "WATCH"

    # ------------------------------------------------------------------
    # 诊断
    # ------------------------------------------------------------------

    def status(self) -> dict:
        """返回各模型加载/训练状态"""
        return {
            "model_dir": str(self.model_dir),
            "market_clf": {
                "loaded": self._loaded["market_clf"],
                "trained": self.market_clf._is_trained,
            },
            "winrate_model": {
                "loaded": self._loaded["winrate"],
                "trained": self.winrate_model._is_trained,
            },
            "rr_model": {
                "loaded": self._loaded["rr"],
                "trained": self.rr_model._is_trained,
            },
        }

    def __repr__(self) -> str:
        s = json.dumps(self.status(), indent=2, ensure_ascii=False)
        return f"ModelManager({self.model_dir})\n{s}"
