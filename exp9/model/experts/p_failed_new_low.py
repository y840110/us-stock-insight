#!/usr/bin/env python3
"""
p_failed_new_low.py — 价格行为学 底部确认信号
=================================================

基于 price action 原理，将"行为确认底部"量化为程序化信号。

核心原理（来自 yudengfeng 的价格行为学教学）：
1. 真正的大底往往发生在所有人都找不到支撑位的时候（历史新低区域）
2. 底部不是预测出来的，是市场行为确认出来的
3. "关键价格不是因为价格本身重要，而是因为市场曾经在这里发生过激烈的多空争夺，并最终证明某一方获胜"

=====================================================================

信号族：FAILED_NEW_LOW 系列（行为确认型底部）

-----------------------------------------------------------------
信号1：FAILED_NEW_LOW
  条件（同时满足）：
  a. 今日价格创新低（低于近20日最低价）
  b. 今日收盘价明显回升（收盘在当日低点上方 > 1%）
  c. 今日成交量 > 20日均量的 1.5倍（放量确认）
  d. SPY 在 200EMA 上方（大盘配合）
  逻辑：空头有能力压创新低，但无力维持，被多头迅速收复 → 底部行为确认

-----------------------------------------------------------------
信号2：HIGHER_LOW_BOUNCE
  条件（同时满足）：
  a. 近3日内出现过新低（低于近20日最低价）
  b. 当前收盘价已经回到（高于）近3日最低价 1% 以上
  c. 当前收盘 > 3日前那根新低K线的收盘价
  d. 反弹日成交量 > 20日均量
  e. SPY 在 200EMA 上方
  逻辑：第一次测试失败（未延续），市场在这里企稳

-----------------------------------------------------------------
信号3：SELLING_CLIMAX_CONFIRM
  条件（同时满足）：
  a. 近5日内有一天是"量能 spike 日"（成交量 > 20日均量 × 2.5）
  b.  Spike日之后3天内，价格没有继续创新低
  c. Spike日之后，价格总体呈上涨态势
  d. SPY 在 200EMA 上方
  逻辑：放量抛售但价格不继续跌 = 机构在接盘 = 底部区域

-----------------------------------------------------------------
信号4：DOUBLE_BOTTOM_CONFIRM
  条件（同时满足）：
  a. 存在两个低点 L1 和 L2，L2 > L1（第二个低点更高）
  b. L1 和 L2 相差不超过 10 个交易日
  c. L2 的最低价不低于 L1 最低价的 95%（即没有显著新低）
  d. 当前价格已经高于 L1 和 L2 之间的那个"谷"
  e. SPY 在 200EMA 上方
  逻辑：二次测试不破前低 = 多头防守成功 = 底部确认

-----------------------------------------------------------------
出场策略（吃中间段）：
  - Measured Move 目标止盈（波段高度 × 0.618）
  - 分批止盈：50% 在 MM 目标位，50% 用 ATR trailing 奔跑
  - 不追求最低点，不追求最高点，吃中间 60-80%

=====================================================================
"""

from typing import List, Dict, Optional, Tuple


def _ema(values: List[float], span: int) -> Optional[float]:
    if len(values) < span:
        return None
    alpha = 2.0 / (span + 1)
    ema = values[0]
    for v in values[1:]:
        ema = alpha * v + (1 - alpha) * ema
    return ema


def _find_swing_lows(bars: List[dict], lookback: int = 20) -> List[Tuple[int, float]]:
    """
    找最近 N 个波段低点
    返回: [(bar_index, low_price), ...]
    """
    if len(bars) < 5:
        return []
    lows = []
    for i in range(3, len(bars) - 3):
        cur_low = float(bars[i]['low'])
        # 局部最低点（前后各3天内最低）
        prev_lows = [float(bars[j]['low']) for j in range(max(0, i-3), min(len(bars), i+4))]
        if cur_low <= min(prev_lows):
            lows.append((i, cur_low))
    return lows[-lookback:]


class FailedNewLowAnalyzer:
    """
    底部行为确认分析器
    基于价格行为学原理，将"市场行为"量化为可交易的信号
    """

    def __init__(self, bars: List[dict], spy_bars: Optional[List[dict]] = None):
        """
        bars: K线数据（list of {date, open, high, low, close, volume}）
        spy_bars: SPY K线数据（用于大盘过滤）
        """
        self.bars = bars
        self.n = len(bars)
        self.closes = [float(b['close']) for b in bars]
        self.opens = [float(b['open']) for b in bars]
        self.highs = [float(b['high']) for b in bars]
        self.lows = [float(b['low']) for b in bars]
        self.volumes = [float(b.get('volume', 0)) for b in bars]
        self.spy_bars = spy_bars

    def _vol_ma(self, period: int = 20) -> float:
        if len(self.volumes) < period:
            return sum(self.volumes) / max(1, len(self.volumes))
        return sum(self.volumes[-period:]) / period

    def _spy_above_ema200(self, idx: int) -> bool:
        """SPY 在 200EMA 上方"""
        if self.spy_bars is None or idx < 200:
            return True  # 无 SPY 数据时默认通过
        spy_closes = [float(b['close']) for b in self.spy_bars[max(0, idx-199):idx+1]]
        if len(spy_closes) < 200:
            return True
        ema200 = _ema(spy_closes, 200)
        if ema200 is None:
            return True
        return spy_closes[-1] > ema200

    def _is_new_20d_low(self, idx: int) -> bool:
        """今日价格是否创20日新低"""
        if idx < 20:
            return False
        cur_low = self.lows[idx]
        recent_lows = self.lows[idx-20:idx]
        return cur_low < min(recent_lows)

    def _is_new_10d_low(self, idx: int) -> bool:
        """今日价格是否创10日新低"""
        if idx < 10:
            return False
        cur_low = self.lows[idx]
        recent_lows = self.lows[idx-10:idx]
        return cur_low < min(recent_lows)

    # ── 信号1：FAILED_NEW_LOW ─────────────────────────────────
    def detect_failed_new_low(self, idx: int) -> Optional[Dict]:
        """
        Failed New Low：
        条件：
        a. 今日创新低（20日新低）
        b. 收盘价在当日低点上方 > 1%（空头无法维持）
        c. 成交量 > 20日均量 × 1.5（放量确认）
        d. SPY 在 200EMA 上方
        """
        if idx < 22 or not self._is_new_20d_low(idx):
            return None

        cur_low = self.lows[idx]
        cur_close = self.closes[idx]
        cur_vol = self.volumes[idx]
        vol_ma20 = self._vol_ma(20)

        # 条件b：收盘收复当日低点 1% 以上
        if cur_low <= 0:
            return None
        recovery_pct = (cur_close - cur_low) / cur_low
        if recovery_pct < 0.01:
            return None

        # 条件c：放量
        if vol_ma20 <= 0 or cur_vol < vol_ma20 * 1.5:
            return None

        # 条件d：SPY 过滤
        if not self._spy_above_ema200(idx):
            return None

        return {
            'signal': 'FAILED_NEW_LOW',
            'type': 'BOTTOM_CONFIRM',
            'confidence': self._calc_confidence(idx, recovery_pct, cur_vol / vol_ma20 if vol_ma20 > 0 else 0),
            'details': {
                'new_low_price': round(cur_low, 2),
                'close_price': round(cur_close, 2),
                'recovery_pct': round(recovery_pct * 100, 1),
                'vol_ratio': round(cur_vol / vol_ma20, 2) if vol_ma20 > 0 else 0,
                'bar_date': self.bars[idx]['date'],
            }
        }

    # ── 信号2：HIGHER_LOW_BOUNCE ─────────────────────────────
    def detect_higher_low_bounce(self, idx: int) -> Optional[Dict]:
        """
        Higher Low Bounce（更高低点反弹）：
        条件：
        a. 近3日内曾创新低（10日新低）
        b. 当前收盘已经回到新低价格上方 1% 以上
        c. SPY 在 200EMA 上方
        """
        if idx < 5:
            return None

        # 找近3日内的新低
        new_low_idx = None
        new_low_price = None
        for lookback in [1, 2, 3]:
            if idx - lookback < 10:
                continue
            if self._is_new_10d_low(idx - lookback):
                new_low_idx = idx - lookback
                new_low_price = self.lows[new_low_idx]
                break

        if new_low_idx is None:
            return None

        # 条件b：当前价格已回到新低上方 1% 以上
        if new_low_price <= 0:
            return None
        bounce_pct = (self.closes[idx] - new_low_price) / new_low_price
        if bounce_pct < 0.01:
            return None

        # 条件c：成交量放大
        vol_ma20 = self._vol_ma(20)
        if vol_ma20 > 0 and self.volumes[idx] < vol_ma20:
            return None  # 反弹需要量能确认

        # 条件d：SPY 过滤
        if not self._spy_above_ema200(idx):
            return None

        return {
            'signal': 'HIGHER_LOW_BOUNCE',
            'type': 'BOTTOM_CONFIRM',
            'confidence': self._calc_confidence(idx, bounce_pct, self.volumes[idx] / vol_ma20 if vol_ma20 > 0 else 0),
            'details': {
                'original_low_idx': new_low_idx,
                'original_low_price': round(new_low_price, 2),
                'bounce_pct': round(bounce_pct * 100, 1),
                'bars_since_low': idx - new_low_idx,
                'bar_date': self.bars[idx]['date'],
            }
        }

    # ── 信号3：SELLING_CLIMAX_CONFIRM ───────────────────────
    def detect_selling_climax(self, idx: int) -> Optional[Dict]:
        """
        Selling Climax（抛售高潮）确认：
        条件：
        a. 近5日内有一天成交量 > 20日均量 × 2.5
        b. Spike日之后3天内价格没有继续创新低（10日新低）
        c. Spike日之后3天内，价格总体呈上涨态势
        d. SPY 在 200EMA 上方
        """
        if idx < 8:
            return None

        vol_ma20 = self._vol_ma(20)
        if vol_ma20 <= 0:
            return None

        # 找近5日内的量能 spike 日
        spike_idx = None
        max_vol_ratio = 0
        for lookback in range(1, min(6, idx)):
            vol_ratio = self.volumes[idx - lookback] / vol_ma20
            if vol_ratio > max_vol_ratio and vol_ratio > 2.5:
                spike_idx = idx - lookback
                max_vol_ratio = vol_ratio

        if spike_idx is None:
            return None

        # 条件b：Spike日之后3天内没有创新10日新低
        # （即：spike_idx 之后到 idx，价格没有创10日新低）
        # 简化：用 spike日之后3天内的收盘价都高于 spike日收盘价的 98%
        # 这意味着价格没有大幅下跌
        spike_close = self.closes[spike_idx]
        price_stayed_up = True
        for j in range(spike_idx + 1, min(idx + 1, spike_idx + 4)):
            if self.closes[j] < spike_close * 0.98:
                price_stayed_up = False
                break

        if not price_stayed_up:
            return None

        # 条件c：Spike日之后价格总体上涨
        if self.closes[idx] <= self.closes[spike_idx]:
            return None

        # 条件d：SPY 过滤
        if not self._spy_above_ema200(idx):
            return None

        total_bounce = (self.closes[idx] - self.closes[spike_idx]) / self.closes[spike_idx]

        return {
            'signal': 'SELLING_CLIMAX_CONFIRM',
            'type': 'BOTTOM_CONFIRM',
            'confidence': self._calc_confidence(idx, total_bounce, max_vol_ratio),
            'details': {
                'spike_idx': spike_idx,
                'spike_date': self.bars[spike_idx]['date'],
                'vol_ratio': round(max_vol_ratio, 2),
                'total_bounce_pct': round(total_bounce * 100, 1),
                'bar_date': self.bars[idx]['date'],
            }
        }

    # ── 信号4：DOUBLE_BOTTOM_CONFIRM ─────────────────────────
    def detect_double_bottom(self, idx: int) -> Optional[Dict]:
        """
        Double Bottom 确认：
        条件：
        a. 存在两个低点 L1 和 L2（L2 略高于 L1，差 < 5%）
        b. L1 和 L2 相差在 5-15 个交易日内
        c. 当前价格已经高于 L1 和 L2 之间的那个谷
        d. SPY 在 200EMA 上方
        """
        if idx < 20:
            return None

        # 找近20天内的波段低点
        swing_lows = _find_swing_lows(self.bars, lookback=20)
        if len(swing_lows) < 2:
            return None

        # 从最近的低点开始，找第二个低点
        # 要求：L2 > L1（更高低点）且差 < 5%，相隔 5-15 天
        for i in range(len(swing_lows) - 2, -1, -1):
            L2_idx, L2_low = swing_lows[-1]  # 最近的低点
            L1_idx, L1_low = swing_lows[i]   # 之前的低点

            # 相隔天数
            days_diff = L2_idx - L1_idx
            if not (5 <= days_diff <= 20):
                continue

            # L2 必须高于 L1（更高低点），但不超过 5%
            if not (L1_low * 1.0 <= L2_low <= L1_low * 1.05):
                continue

            # 找 L1 和 L2 之间的那个"谷"（最低点）
            valley_idx = L1_idx
            valley_low = L2_low  # 从 L1 到 L2 之间的最低点
            for j in range(L1_idx, L2_idx + 1):
                if self.lows[j] < valley_low:
                    valley_low = self.lows[j]
                    valley_idx = j

            # 当前价格需要高于 valley
            if self.closes[idx] <= valley_low:
                continue

            # SPY 过滤
            if not self._spy_above_ema200(idx):
                continue

            return {
                'signal': 'DOUBLE_BOTTOM_CONFIRM',
                'type': 'BOTTOM_CONFIRM',
                'confidence': self._calc_confidence(idx, (self.closes[idx] - L1_low) / L1_low, 1.0),
                'details': {
                    'L1_idx': L1_idx,
                    'L1_low': round(L1_low, 2),
                    'L2_idx': L2_idx,
                    'L2_low': round(L2_low, 2),
                    'days_between': days_diff,
                    'valley_idx': valley_idx,
                    'valley_low': round(valley_low, 2),
                    'bar_date': self.bars[idx]['date'],
                }
            }

        return None

    # ── 综合分析 ───────────────────────────────────────────
    def analyze(self, idx: int) -> Dict:
        """
        对指定 bar 进行全面底部分析
        返回所有检测到的信号
        """
        signals = []

        # 检测所有4个信号
        for detector in [
            self.detect_failed_new_low,
            self.detect_higher_low_bounce,
            self.detect_selling_climax,
            self.detect_double_bottom,
        ]:
            result = detector(idx)
            if result is not None:
                signals.append(result)

        if not signals:
            return {
                'has_signal': False,
                'signals': [],
                'primary_signal': None,
                'overall_regime': self._get_regime(idx),
            }

        # 按 confidence 排序，取最高
        signals.sort(key=lambda x: x['confidence'], reverse=True)
        primary = signals[0]

        return {
            'has_signal': True,
            'signals': signals,
            'primary_signal': primary['signal'],
            'primary_confidence': primary['confidence'],
            'overall_regime': self._get_regime(idx),
            'details': primary['details'],
        }

    def _calc_confidence(self, idx: int, recovery_pct: float, vol_ratio: float) -> float:
        """
        计算信号置信度（0-100）
        综合考虑：反弹幅度、量能放大程度、整体趋势
        """
        # 反弹幅度得分（0-40）
        recovery_score = min(40, recovery_pct * 400)

        # 量能得分（0-30）
        vol_score = min(30, (vol_ratio - 1.0) * 20) if vol_ratio > 1.0 else 0

        # 趋势确认（0-30）：收盘是否在20EMA上方
        if idx >= 20:
            ema20_vals = self.closes[idx-19:idx+1]
            if len(ema20_vals) >= 20:
                ema20 = _ema(ema20_vals, 20)
                if ema20 and self.closes[idx] > ema20:
                    trend_score = 30
                elif ema20 and self.closes[idx] > ema20 * 0.95:
                    trend_score = 15
                else:
                    trend_score = 0
            else:
                trend_score = 15
        else:
            trend_score = 15

        return round(recovery_score + vol_score + trend_score, 1)

    def _get_regime(self, idx: int) -> str:
        """判断当前 regime"""
        if idx < 30:
            return 'UNKNOWN'

        # 20日均线方向
        if idx >= 22:
            ema20_recent = _ema(self.closes[idx-19:idx+1], 20)
            ema20_old = _ema(self.closes[idx-24:idx-4], 20)
            if ema20_recent and ema20_old:
                if ema20_recent > ema20_old * 1.02:
                    trend = 'UP'
                elif ema20_recent < ema20_old * 0.98:
                    trend = 'DOWN'
                else:
                    trend = 'RANGE'
            else:
                trend = 'RANGE'
        else:
            trend = 'RANGE'

        # 波动率
        if idx >= 15:
            trs = []
            for j in range(max(1, idx-14), idx+1):
                h, l = self.highs[j], self.lows[j]
                pc = self.closes[j-1]
                tr = max(h - l, abs(h - pc), abs(l - pc))
                trs.append(tr)
            if trs:
                avg_tr = sum(trs) / len(trs)
                recent_atr = avg_tr
                old_trs = []
                for j in range(max(1, idx-29), max(1, idx-14)):
                    h, l = self.highs[j], self.lows[j]
                    pc = self.closes[j-1]
                    tr = max(h - l, abs(h - pc), abs(l - pc))
                    old_trs.append(tr)
                if old_trs:
                    old_atr = sum(old_trs) / len(old_trs)
                    if recent_atr > old_atr * 1.3:
                        regime = 'HIGH_VOL'
                    elif recent_atr < old_atr * 0.7:
                        regime = 'LOW_VOL'
                    else:
                        regime = 'NORMAL_VOL'
                else:
                    regime = 'NORMAL_VOL'
            else:
                regime = 'NORMAL_VOL'
        else:
            regime = 'NORMAL_VOL'

        return f'{trend}_{regime}'


# ── 独立测试 ──────────────────────────────────────────────────
if __name__ == '__main__':
    import sys, json
    from pathlib import Path

    # 加载测试数据
    base = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(base / 'model' / 'experts'))
    from p_buy_filter_v2 import load_klines

    ticker = 'AMZN'
    bars = load_klines(ticker, lookback=300)
    print(f'Loaded {len(bars)} bars for {ticker}')

    analyzer = FailedNewLowAnalyzer(bars)

    # 扫描最近 60 天，找所有底部信号
    print('\n=== 底部信号扫描（最近60天）===')
    for i in range(60, len(bars)):
        result = analyzer.analyze(i)
        if result['has_signal']:
            print(f"\n  {bars[i]['date']} | {result['primary_signal']} "
                  f"(confidence={result['primary_confidence']})")
            print(f"    regime: {result['overall_regime']}")
            details = result.get('details', {})
            for k, v in details.items():
                print(f"    {k}: {v}")
