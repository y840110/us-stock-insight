"""
综合信号生成器：规则评分 + ML混合确认 + 盈亏比计算
"""

from typing import TypedDict, Optional
from .factor_scorer import calc_composite_score


class Signal(TypedDict):
    """generate() 返回类型"""
    signal: str                    # 'LONG' | 'WATCH' | 'ABANDON'
    score: int                      # 总评分 0~100
    rating: str                     # 'A+' | 'A' | 'B' | 'C' | 'D'
    position_size: float            # 1.0 | 0.5 | 0.25 | 0.0
    ml_confirmed: bool              # ML是否验证通过
    structure_type: str             # 'A+' | 'A' | 'B'
    entry_price: Optional[float]   # 建议入场价（当日收盘）
    stop_loss: Optional[float]      # 建议止损价
    target: Optional[float]          # 建议目标价
    rr_ratio: Optional[float]       # 盈亏比（target - entry) / (entry - stop_loss)
    reason: list[str]               # 入场/不看理由列表


class SignalGenerator:
    """
    综合信号生成器

    支持三种模式：
    1. 纯规则（factor_scorer） — 不传 ml_prob_up
    2. ML模型确认 — 传入 ml_prob_up
    3. 混合 — 规则 + ML 双重确认
    """

    # 止损/目标参数（可实例化时覆盖）
    DEFAULT_STOP_LOSS_PCT: float = 0.05   # 默认止损 5%
    DEFAULT_TARGET_PCT: float = 0.20       # 默认目标 20%

    def __init__(
        self,
        stop_loss_pct: float = DEFAULT_STOP_LOSS_PCT,
        target_pct: float = DEFAULT_TARGET_PCT,
    ) -> None:
        """
        Args:
            stop_loss_pct: 止损幅度（相对入场价），默认 5%
            target_pct: 目标幅度（相对入场价），默认 20%
        """
        self.stop_loss_pct = stop_loss_pct
        self.target_pct = target_pct

    # ------------------------------------------------------------------
    # 核心方法
    # ------------------------------------------------------------------

    def generate(
        self,
        factors: dict,
        ml_prob_up: Optional[float] = None,
        ml_expected_rr: Optional[float] = None,
    ) -> Signal:
        """
        生成综合交易信号

        Args:
            factors: calc_all_factors() 输出的完整因子字典
            ml_prob_up: ML模型预测上涨概率（0~1），可选
            ml_expected_rr: ML模型预期盈亏比，可选

        Returns:
            Signal dict:
            {
                'signal': 'LONG' | 'WATCH' | 'ABANDON',
                'score': int,
                'rating': str,
                'position_size': float,
                'ml_confirmed': bool,
                'structure_type': str,          # 'A+' / 'A' / 'B'
                'entry_price': float | None,
                'stop_loss': float | None,
                'target': float | None,
                'rr_ratio': float | None,
                'reason': list[str],
            }
        """
        # 1. 基础评分
        cs = calc_composite_score(factors)
        score = cs["total_score"]
        rating = cs["rating"]
        position_size = cs["position_size"]

        # 2. 获取入场价（当日收盘）
        entry_price = self._extract_entry_price(factors)

        # 3. 构建 reason 列表
        reasons = self._build_reasons(factors, cs)

        # 4. ML 混合模式
        ml_confirmed = False
        structure_type = rating  # 默认用规则评级

        if ml_prob_up is not None:
            ml_confirmed, structure_type = self._ml_confirm(
                score=score,
                ml_prob_up=ml_prob_up,
                ml_expected_rr=ml_expected_rr,
                base_rating=rating,
            )

        # 5. 综合信号 + 盈亏比（由 _resolve_signal 统一计算）
        signal, position_size, stop_loss, target, rr_ratio = self._resolve_signal(
            score=score,
            ml_prob_up=ml_prob_up,
            ml_expected_rr=ml_expected_rr,
            ml_confirmed=ml_confirmed,
            base_position=position_size,
            entry_price=entry_price,
        )

        # 6. structure_type：ML 确认时保留 _ml_confirm 结果；纯规则时按评分档位
        if not ml_confirmed:
            if signal == "LONG" and score >= 85:
                structure_type = "A+"
            elif signal == "LONG" and score >= 75:
                structure_type = "A"
            elif signal == "WATCH":
                structure_type = "B"
            else:
                structure_type = "D"

        return Signal(
            signal=signal,
            score=score,
            rating=structure_type,  # 用 ML 调整后的评级覆盖
            position_size=position_size,
            ml_confirmed=ml_confirmed,
            structure_type=structure_type,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target=target,
            rr_ratio=rr_ratio,
            reason=reasons,
        )

    def generate_batch(self, stocks: list[dict]) -> list[dict]:
        """
        批量生成信号，返回排序后的股票列表（按评分降序）

        Args:
            stocks: 元素为完整因子字典的列表

        Returns:
            同输入顺序，但每个元素追加 signal 结果，并按 score 降序排列
        """
        results = []
        for factors in stocks:
            sig = self.generate(factors)
            merged = {**factors, **sig}
            results.append(merged)

        # 按评分降序排列
        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return results

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    def _ml_confirm(
        self,
        score: int,
        ml_prob_up: float,
        ml_expected_rr: Optional[float],
        base_rating: str,
    ) -> tuple[bool, str]:
        """
        ML 确认逻辑，返回 (ml_confirmed, structure_type)

        ML 混合模式规则：
        - score ≥ 75 AND ml_prob_up > 0.65 AND ml_expected_rr > 1.5 → LONG 1.0
        - score ≥ 75 AND ml_prob_up > 0.55 → LONG 0.5
        - score < 60 OR ml_prob_up < 0.50 → ABANDON
        - ELSE → WATCH 0.25
        """
        if score >= 75 and ml_prob_up > 0.65:
            if ml_expected_rr is not None and ml_expected_rr > 1.5:
                return True, "A+"
            return True, "A"
        elif score >= 75 and ml_prob_up > 0.55:
            return True, "A"
        elif score < 60 or ml_prob_up < 0.50:
            return False, "D"
        else:
            return False, "B"

    def _resolve_signal(
        self,
        score: int,
        ml_prob_up: Optional[float],
        ml_expected_rr: Optional[float],
        ml_confirmed: bool,
        base_position: float,
        entry_price: Optional[float],
    ) -> tuple[str, float, Optional[float], Optional[float], Optional[float]]:
        """综合规则 + ML 决定最终信号、仓位、止损/目标"""
        # 无 ML：走纯规则
        if ml_prob_up is None:
            if score >= 75:
                signal = "LONG"
                position = base_position
            elif score >= 60:
                signal = "WATCH"
                position = 0.25
            else:
                signal = "ABANDON"
                position = 0.0
            stop_loss, target, rr_ratio = self._calc_entry_exit(entry_price)
            return signal, position, stop_loss, target, rr_ratio

        # ML 混合模式（已在 _ml_confirm 中确认过，这里只决定最终信号）
        if score >= 75 and ml_prob_up > 0.65:
            if ml_expected_rr is not None and ml_expected_rr > 1.5:
                signal = "LONG"
                position = 1.0
            else:
                signal = "LONG"
                position = 0.5
        elif score >= 75 and ml_prob_up > 0.55:
            signal = "LONG"
            position = 0.5
        elif score < 60 or ml_prob_up < 0.50:
            signal = "ABANDON"
            position = 0.0
        else:
            signal = "WATCH"
            position = 0.25

        return signal, position, *self._calc_entry_exit(entry_price)

    def _calc_entry_exit(
        self, entry_price: Optional[float]
    ) -> tuple[Optional[float], Optional[float], Optional[float]]:
        """计算止损、目标、盈亏比"""
        if entry_price is None:
            return None, None, None

        stop_loss = round(entry_price * (1 - self.stop_loss_pct), 2)
        target = round(entry_price * (1 + self.target_pct), 2)
        rr_ratio = round((target - entry_price) / (entry_price - stop_loss), 2) if stop_loss else None

        return stop_loss, target, rr_ratio

    def _extract_entry_price(self, factors: dict) -> Optional[float]:
        """从因子字典提取最新收盘价作为入场价（以 ymd 为锚点）"""
        data = factors.get("data", [])
        if not data:
            return None
        if isinstance(data, list) and len(data) > 0:
            # 显式排序找最新（兼容正序或倒序文件）
            sorted_data = sorted(data, key=lambda x: x.get('ymd', x.get('date', '')))
            last = sorted_data[-1]
            if isinstance(last, dict):
                return float(last.get("close", 0)) or None
        return None

    def _build_reasons(self, factors: dict, cs: dict) -> list[str]:
        """构建入场/不看好的理由列表"""
        reasons: list[str] = []

        # 市场
        if factors.get("spy_above_200ema"):
            reasons.append("✅ SPY 在 200EMA 上方，市场多头结构")
        else:
            reasons.append("⚠️ SPY 在 200EMA 下方，市场偏空")

        if factors.get("vix") and factors.get("vix") > 25:
            reasons.append(f"⚠️ VIX={factors['vix']} > 25，高波动风险")

        # RS
        rs_20d = factors.get("rs_20d", 0)
        if rs_20d > 5:
            reasons.append(f"✅ RS20D={rs_20d:.2f}%，相对大盘强势")
        elif rs_20d < 0:
            reasons.append(f"⚠️ RS20D={rs_20d:.2f}%，相对大盘弱势")

        # 趋势
        if factors.get("ema50_above_ema200"):
            reasons.append("✅ 日线 EMA50 > 200 EMA，多头排列")
        if factors.get("above_20ema") and factors.get("above_50ema"):
            reasons.append("✅ 价格在 20EMA 和 50EMA 上方")

        # 量能
        if factors.get("breakout_volume"):
            reasons.append("✅ 放量突破（量比 > 1.5 + 价格上涨）")
        if factors.get("pullback_shrinking"):
            reasons.append("✅ 回踩缩量确认（量能收缩）")

        # 波动率
        atr_pct = factors.get("atr_pct", 0)
        if atr_pct > 5:
            reasons.append(f"⚠️ ATR%={atr_pct:.2f}% > 5%，高波动")
        elif atr_pct < 1:
            reasons.append(f"ℹ️ ATR%={atr_pct:.2f}% < 1%，低波动")

        # 综合评分说明
        score = cs["total_score"]
        rating = cs["rating"]
        reasons.append(f"📊 综合评分：{score}/100（{rating}档）")

        return reasons


# ----------------------------------------------------------------------
# 单元测试
# ----------------------------------------------------------------------
if __name__ == "__main__":
    # 构造一个 dummy 因子字典
    dummy_klines_data = [
        {"ymd": "2024-01-01", "open": 180, "high": 185, "low": 179, "close": 183, "adj": 183, "vol": 50e6},
        {"ymd": "2024-01-02", "open": 183, "high": 188, "low": 182, "close": 186, "adj": 186, "vol": 55e6},
        {"ymd": "2024-01-03", "open": 186, "high": 190, "low": 185, "close": 189, "adj": 189, "vol": 60e6},
    ]

    def make_factors(**kwargs) -> dict:
        defaults = dict(
            data=dummy_klines_data,
            market_score=25,
            rs_score=22,
            trend_score=18,
            volume_score=12,
            vol_score=8,
            spy_above_200ema=True,
            vix=18.0,
            rs_20d=8.5,
            ema50_above_ema200=True,
            above_20ema=True,
            above_50ema=True,
            breakout_volume=True,
            pullback_shrinking=True,
            atr_pct=2.5,
        )
        defaults.update(kwargs)
        return defaults

    sg = SignalGenerator()

    # 测试1：纯规则 A+ → LONG 1.0
    f = make_factors(
        market_score=30, rs_score=25, trend_score=20,
        volume_score=15, vol_score=10,
    )
    r = sg.generate(f)
    assert r["signal"] == "LONG"
    assert r["position_size"] == 1.0
    assert r["score"] == 100
    print(f"✅ A+ 规则测试通过：{r['signal']}, {r['position_size']}")

    # 测试2：A 档边界 → LONG 0.5
    f = make_factors(
        market_score=30, rs_score=25, trend_score=20,
        volume_score=0, vol_score=0,
    )
    r = sg.generate(f)
    assert r["signal"] == "LONG"
    assert r["position_size"] == 0.5
    print(f"✅ A 档测试通过：{r['signal']}, {r['position_size']}")

    # 测试3：B 档 → WATCH
    f = make_factors(
        market_score=15, rs_score=20, trend_score=15,
        volume_score=10, vol_score=5,
    )
    r = sg.generate(f)
    assert r["signal"] == "WATCH"
    assert r["position_size"] == 0.25
    print(f"✅ B 档测试通过：{r['signal']}, {r['position_size']}")

    # 测试4：ML 强化 → ml_prob_up=0.7, score=80 → LONG 1.0
    f = make_factors(
        market_score=25, rs_score=22, trend_score=18,
        volume_score=10, vol_score=5,
    )
    r = sg.generate(f, ml_prob_up=0.70, ml_expected_rr=2.0)
    assert r["signal"] == "LONG"
    assert r["ml_confirmed"] is True
    assert r["structure_type"] == "A+"
    print(f"✅ ML 强化测试通过：{r['signal']}, ml_confirmed={r['ml_confirmed']}")

    # 测试5：ML 弱化 → score=70, ml_prob_up=0.45 → ABANDON
    f = make_factors(
        market_score=20, rs_score=20, trend_score=15,
        volume_score=10, vol_score=5,
    )
    r = sg.generate(f, ml_prob_up=0.45)
    assert r["signal"] == "ABANDON"
    assert r["position_size"] == 0.0
    print(f"✅ ML 弱化测试通过：{r['signal']}")

    # 测试6：generate_batch 排序
    batch = [
        make_factors(market_score=10, rs_score=10, trend_score=10, volume_score=5, vol_score=5),  # 40
        make_factors(market_score=30, rs_score=25, trend_score=20, volume_score=15, vol_score=10),  # 100
        make_factors(market_score=20, rs_score=15, trend_score=15, volume_score=10, vol_score=5),   # 65
    ]
    results = sg.generate_batch(batch)
    scores = [x["score"] for x in results]
    assert scores == [100, 65, 40], f"排序失败：{scores}"
    print(f"✅ 批量排序测试通过：{[x['rating'] for x in results]}")

    # 测试7：止损/目标/盈亏比
    f = make_factors(data=dummy_klines_data)
    r = sg.generate(f)
    assert r["entry_price"] == 189.0
    assert r["stop_loss"] == round(189 * 0.95, 2)  # 5% 止损
    assert r["target"] == round(189 * 1.20, 2)      # 20% 目标
    expected_rr = round((189 * 1.20 - 189) / (189 - 189 * 0.95), 2)
    assert r["rr_ratio"] == expected_rr
    print(f"✅ 盈亏比测试通过：RR={r['rr_ratio']}")

    # 测试8：reasons 包含评分说明
    r = sg.generate(f)
    assert any("📊 综合评分" in s for s in r["reason"]), "reasons 缺少评分说明"
    print(f"✅ reasons 列表测试通过：{len(r['reason'])} 条理由")

    print("\n🎉 所有 SignalGenerator 单元测试通过！")
