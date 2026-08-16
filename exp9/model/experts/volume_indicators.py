#!/usr/bin/env python3
"""
volume_indicators.py — 成交量指标体系
==========================================

基于专业量化策略设计的量价指标，用于日线顶底判断

核心指标：
1. OBV (On-Balance Volume)        — 累积派发线，量价背离
2. MFI (Money Flow Index)          — 资金流量指数（量加权RSI）
3. Chaikin Money Flow (CMF)        — 积累/派发指标
4. VWAP Deviation                  — 价格相对均线的偏离
5. Volume Spike                    — 量能异常放大检测
6. ATR Volatility Regime            — 波动率 regime 切换
7. ADX (Average Directional Index)  — 趋势强度
8. Aroon Indicator                 — 趋势顶底转换

用法：
    from volume_indicators import VolumeAnalyzer
    va = VolumeAnalyzer(bars)  # bars = list of {open, high, low, close, volume}
    signals = va.analyze()
"""

import math
from typing import List, Dict, Optional


def _ema(values: List[float], span: int) -> Optional[float]:
    if len(values) < span:
        return None
    alpha = 2.0 / (span + 1)
    ema = values[0]
    for v in values[1:]:
        ema = alpha * v + (1 - alpha) * ema
    return ema


class VolumeAnalyzer:
    """量价分析器 — 基于日线数据"""

    def __init__(self, bars: List[dict], lookback: int = 100):
        self.bars = bars[-lookback:]
        self.n = len(self.bars)
        self.closes = [float(b['close']) for b in self.bars]
        self.opens = [float(b['open']) for b in self.bars]
        self.highs = [float(b['high']) for b in self.bars]
        self.lows = [float(b['low']) for b in self.bars]
        self.volumes = [float(b.get('volume', 0)) for b in self.bars]

    # ── 1. OBV ──────────────────────────────────────────
    def obv(self, period: int = 20) -> Dict:
        """
        OBV = 累积(Volume × sign(close - prev_close))
        创新高但OBV不再创新高 = 顶背离（派发）
        创新低但OBV不再创新低 = 底背离（积累）
        """
        if self.n < 3:
            return {'value': 0, 'signal': 'NEUTRAL'}

        obv_values = [self.volumes[0]]
        for i in range(1, self.n):
            if self.closes[i] > self.closes[i-1]:
                obv_values.append(obv_values[-1] + self.volumes[i])
            elif self.closes[i] < self.closes[i-1]:
                obv_values.append(obv_values[-1] - self.volumes[i])
            else:
                obv_values.append(obv_values[-1])

        obv_ema = _ema(obv_values, period)
        current_obv = obv_values[-1]
        max_obv_20 = max(obv_values[-20:]) if len(obv_values) >= 20 else max(obv_values)
        min_obv_20 = min(obv_values[-20:]) if len(obv_values) >= 20 else min(obv_values)

        # 价格创新高但OBV未创新高 = 顶背离
        price_high_20 = max(self.highs[-20:]) if len(self.highs) >= 20 else max(self.highs)
        price_now_highest = self.highs[-1] >= price_high_20 * 0.99
        obv_not_highest = current_obv < max_obv_20 * 0.97

        # 价格创新低但OBV未创新低 = 底背离
        price_low_20 = min(self.lows[-20:]) if len(self.lows) >= 20 else min(self.lows)
        price_now_lowest = self.lows[-1] <= price_low_20 * 1.01
        obv_not_lowest = current_obv > min_obv_20 * 1.03

        if price_now_highest and obv_not_highest:
            signal = 'BEARISH_DIVERGENCE'  # 顶背离 = 可能顶部
        elif price_now_lowest and obv_not_lowest:
            signal = 'BULLISH_DIVERGENCE'  # 底背离 = 可能底部
        elif obv_ema is not None and current_obv > obv_ema:
            signal = 'OBV_BULLISH'
        elif obv_ema is not None and current_obv < obv_ema:
            signal = 'OBV_BEARISH'
        else:
            signal = 'NEUTRAL'

        return {
            'value': current_obv,
            'ema': obv_ema,
            'signal': signal,
            'price_high_20': price_high_20,
            'price_low_20': price_low_20,
            'divergence_type': signal if 'DIVERGENCE' in signal else None,
        }

    # ── 2. MFI (Money Flow Index) ──────────────────────
    def mfi(self, period: int = 14) -> Dict:
        """
        MFI = 100 - (100 / (1 + Money Flow Ratio))
        Money Flow = Typical Price × Volume
        >80 = 超买（潜在顶部），<20 = 超卖（潜在底部）
        MFI创新高 + 价格不创新高 = 顶背离
        """
        if self.n < period + 1:
            return {'value': 50, 'signal': 'NEUTRAL'}

        typical_prices = [
            (float(b['high']) + float(b['low']) + float(b['close'])) / 3
            for b in self.bars
        ]
        money_flows = [tp * float(self.bars[i].get('volume', 0))
                       for i, tp in enumerate(typical_prices)]

        # 正向/负向资金流
        pos_flow = sum(money_flows[i] for i in range(1, self.n)
                       if typical_prices[i] > typical_prices[i-1])
        neg_flow = sum(money_flows[i] for i in range(1, self.n)
                       if typical_prices[i] < typical_prices[i-1])

        if neg_flow == 0:
            mfi_value = 100.0
        else:
            mr = pos_flow / neg_flow
            mfi_value = 100 - (100 / (1 + mr))
        mfi_value = max(0, min(100, mfi_value))

        # MFI 背离检测
        mfi_highs = []
        mfi_lows = []
        for i in range(3, self.n):
            if typical_prices[i] > typical_prices[i-1] > typical_prices[i-2]:
                mfi_highs.append(typical_prices[i])
            if typical_prices[i] < typical_prices[i-1] < typical_prices[i-2]:
                mfi_lows.append(typical_prices[i])

        price_trend_up = self.closes[-1] > self.closes[-5] if self.n >= 5 else False
        price_trend_dn = self.closes[-1] < self.closes[-5] if self.n >= 5 else False

        # MFI > 80 且 价格停止上涨 = 顶部风险
        if mfi_value > 80:
            if not price_trend_up:
                signal = 'MFI_OVERBOUGHT_TOP_RISK'
            else:
                signal = 'MFI_OVERBOUGHT'
        elif mfi_value < 20:
            if not price_trend_dn:
                signal = 'MFI_OVERSOLD_BOTTOM_RISK'
            else:
                signal = 'MFI_OVERSOLD'
        elif mfi_value > 60:
            signal = 'MFI_BULLISH'
        elif mfi_value < 40:
            signal = 'MFI_BEARISH'
        else:
            signal = 'NEUTRAL'

        return {
            'value': mfi_value,
            'signal': signal,
            'overbought': mfi_value > 80,
            'oversold': mfi_value < 20,
        }

    # ── 3. Chaikin Money Flow (CMF) ───────────────────
    def cmf(self, period: int = 20) -> Dict:
        """
        CMF = Σ(((Close - Low) - (High - Close)) / (High - Low) × Volume) / Σ(Volume)
        CMF > 0 = 积累（机构买入），CMF < 0 = 派发（机构卖出）
        CMF 由负转正 = 潜在底部；CMF 由正转负 = 潜在顶部
        """
        if self.n < period + 1:
            return {'value': 0, 'signal': 'NEUTRAL'}

        clv_values = []
        for b in self.bars:
            h, l, c = float(b['high']), float(b['low']), float(b['close'])
            if h == l:
                clv_values.append(0)
            else:
                clv_values.append((c - l - (h - c)) / (h - l))

        cmf_sum = 0.0
        vol_sum = 0.0
        for i in range(max(0, self.n - period), self.n):
            cmf_sum += clv_values[i] * self.volumes[i]
            vol_sum += self.volumes[i]

        cmf_value = cmf_sum / vol_sum if vol_sum > 0 else 0

        # 检测趋势
        prev_cmf_sum = 0.0
        prev_vol_sum = 0.0
        for i in range(max(0, self.n - 2*period), max(0, self.n - period)):
            prev_cmf_sum += clv_values[i] * self.volumes[i]
            prev_vol_sum += self.volumes[i]
        prev_cmf = prev_cmf_sum / prev_vol_sum if prev_vol_sum > 0 else 0

        if cmf_value > 0.05 and prev_cmf <= 0:
            signal = 'CMF_BULLISH_CROSS'  # 积累信号
        elif cmf_value < -0.05 and prev_cmf >= 0:
            signal = 'CMF_BEARISH_CROSS'  # 派发信号
        elif cmf_value > 0.1:
            signal = 'CMF_STRONG_ACCUMULATION'
        elif cmf_value < -0.1:
            signal = 'CMF_STRONG_DISTRIBUTION'
        elif cmf_value > 0:
            signal = 'CMF_BULLISH'
        elif cmf_value < 0:
            signal = 'CMF_BEARISH'
        else:
            signal = 'NEUTRAL'

        return {
            'value': cmf_value,
            'signal': signal,
            'accumulating': cmf_value > 0,
            'cross_up': cmf_value > 0.05 and prev_cmf <= 0,
            'cross_down': cmf_value < -0.05 and prev_cmf >= 0,
        }

    # ── 4. VWAP Deviation ─────────────────────────────
    def vwap_deviation(self, period: int = 20) -> Dict:
        """
        VWAP = Σ(Price × Volume) / Σ(Volume)
        价格 > VWAP × 1.03 = 强势，价格 > VWAP × 1.10 = 可能过热
        价格 < VWAP × 0.97 = 弱势，价格 < VWAP × 0.90 = 可能超卖
        """
        if self.n < 5:
            return {'vwap': self.closes[-1] if self.closes else 0, 'deviation': 0, 'signal': 'NEUTRAL'}

        pv_sum = sum(self.closes[i] * self.volumes[i] for i in range(self.n))
        vol_sum = sum(self.volumes[i] for i in range(self.n))
        vwap = pv_sum / vol_sum if vol_sum > 0 else self.closes[-1]
        current = self.closes[-1]
        deviation = (current - vwap) / vwap if vwap > 0 else 0

        if deviation > 0.10:
            signal = 'EXTREME_OVERPRICED'  # 过热
        elif deviation > 0.03:
            signal = 'ABOVE_VWAP_STRONG'
        elif deviation < -0.10:
            signal = 'EXTREME_UNDERPRICED'  # 超卖
        elif deviation < -0.03:
            signal = 'BELOW_VWAP_WEAK'
        else:
            signal = 'NEAR_VWAP'

        return {
            'vwap': vwap,
            'deviation': deviation,
            'signal': signal,
            'pct_from_vwap': deviation * 100,
        }

    # ── 5. Volume Spike Detection ──────────────────────
    def volume_spike(self, period: int = 20, mult: float = 2.0) -> Dict:
        """
        检测量能异常放大
        量 > 均值 × mult = 量能 spike
        顶部的量能 spike = 可能的派发（机构出货）
        底部的量能 spike = 可能的积累（机构吸筹）
        """
        if self.n < period + 1:
            return {'spike': False, 'signal': 'NEUTRAL'}

        vol_ma = sum(self.volumes[-(period):]) / period
        current_vol = self.volumes[-1]
        vol_ratio = current_vol / vol_ma if vol_ma > 0 else 0

        # 检测 spike 发生位置
        price_trend = self.closes[-1] - self.closes[-5] if self.n >= 5 else 0
        spike = vol_ratio > mult

        if spike and price_trend > 0:
            # 价格上涨 + 量能 spike = 可疑（可能是顶部派发）
            signal = 'VOL_SPIKE_TOP'  # 顶部量能异常 = 小心
        elif spike and price_trend < 0:
            # 价格下跌 + 量能 spike = 积累信号（恐慌抛售后机构接盘）
            signal = 'VOL_SPIKE_BOTTOM'
        elif spike:
            signal = 'VOL_SPIKE'
        else:
            signal = 'NORMAL_VOLUME'

        return {
            'spike': spike,
            'vol_ratio': vol_ratio,
            'vol_ma': vol_ma,
            'current_vol': current_vol,
            'signal': signal,
        }

    # ── 6. ATR Volatility Regime ───────────────────────
    def atr_regime(self, period: int = 14) -> Dict:
        """
        ATR 波动率 regime 检测
        ATR 由低变高 = 波动率爆发（趋势开始或反转）
        ATR 由高变低 = 波动率收缩（盘整）
        """
        if self.n < period + 20:
            return {'atr': 0, 'regime': 'UNKNOWN', 'signal': 'NEUTRAL'}

        trs = []
        for i in range(1, self.n):
            h, l, pc = self.highs[i], self.lows[i], self.closes[i-1]
            tr = max(h - l, abs(h - pc), abs(l - pc))
            trs.append(tr)

        atr_current = sum(trs[-period:]) / period if len(trs) >= period else 0
        atr_prev = sum(trs[-period-5:-5]) / period if len(trs) >= period + 5 else atr_current
        atr_prev20 = sum(trs[-(period+20):-20]) / period if len(trs) >= period + 20 else atr_current

        # ATR regime
        if atr_current > atr_prev20 * 1.5:
            regime = 'HIGH_VOLATILITY'
        elif atr_current < atr_prev20 * 0.7:
            regime = 'LOW_VOLATILITY'
        else:
            regime = 'NORMAL_VOLATILITY'

        # ATR 变化
        atr_change = (atr_current - atr_prev) / atr_prev if atr_prev > 0 else 0

        if atr_change > 0.3 and regime == 'HIGH_VOLATILITY':
            signal = 'VOLATILITY_EXPLOSION'  # 波动率爆发
        elif atr_change < -0.2:
            signal = 'VOLATILITY_CONTRACTION'  # 波动率收缩
        else:
            signal = 'VOLATILITY_STABLE'

        return {
            'atr': atr_current,
            'regime': regime,
            'atr_change': atr_change,
            'signal': signal,
        }

    # ── 7. ADX (趋势强度) ─────────────────────────────
    def adx(self, period: int = 14) -> Dict:
        """
        ADX > 25 = 趋势明确，ADX > 40 = 极强趋势
        ADX 上升 = 趋势在加强，ADX 下降 = 趋势在减弱
        +DI > -DI = 多头趋势，-DI > +DI = 空头趋势
        """
        if self.n < period * 2:
            return {'adx': 0, 'signal': 'NO_TREND'}

        # 计算 +DI, -DI, DX
        def dmi(period: int):
            plus_dm, minus_dm = [], []
            for i in range(1, self.n):
                h_curr, l_curr = self.highs[i], self.lows[i]
                h_prev, l_prev = self.highs[i-1], self.lows[i-1]
                up_move = h_curr - h_prev
                down_move = l_prev - l_curr
                plus_dm.append(max(up_move, 0) if up_move > down_move else 0)
                minus_dm.append(max(down_move, 0) if down_move > up_move else 0)

            tr = []
            for i in range(1, self.n):
                h, l, pc = self.highs[i], self.lows[i], self.closes[i-1]
                tr.append(max(h-l, abs(h-pc), abs(l-pc)))

            if len(tr) < period:
                return 0, 0, 0

            atr_s = sum(tr[-period:]) / period
            plus_di = (sum(plus_dm[-period:]) / atr_s * 100) if atr_s > 0 else 0
            minus_di = (sum(minus_dm[-period:]) / atr_s * 100) if atr_s > 0 else 0
            di_sum = plus_di + minus_di
            dx = (abs(plus_di - minus_di) / di_sum * 100) if di_sum > 0 else 0

            return plus_di, minus_di, dx

        plus_di, minus_di, dx = dmi(period)
        adx_vals = []
        for i in range(period, len(self.closes)):
            _, _, dx_i = dmi(period)
            adx_vals.append(dx_i)
        adx = _ema(adx_vals, period) if len(adx_vals) >= period else 0

        if adx > 40:
            signal = 'STRONG_TREND'
        elif adx > 25:
            signal = 'TREND'
        else:
            signal = 'NO_TREND'

        if plus_di > minus_di:
            trend_dir = 'BULLISH'
        else:
            trend_dir = 'BEARISH'

        return {
            'adx': adx,
            'plus_di': plus_di,
            'minus_di': minus_di,
            'signal': signal,
            'trend_dir': trend_dir,
        }

    # ── 8. Aroon Indicator ──────────────────────────────
    def aroon(self, period: int = 25) -> Dict:
        """
        Aroon Up = 从最近高点经过的周期数 / 总周期数
        Aroon Down = 从最近低点经过的周期数 / 总周期数
        Aroon Up > 70 且 Aroon Down < 30 = 强势上涨
        Aroon Down > 70 且 Aroon Up < 30 = 强势下跌
        Aroon 交叉 = 趋势转换信号
        """
        if self.n < period + 1:
            return {'aroon_up': 50, 'aroon_down': 50, 'signal': 'NEUTRAL'}

        closes = self.closes[-period:]
        max_idx = closes.index(max(closes))  # 距离今天最近高点
        min_idx = closes.index(min(closes))  # 距离今天最近低点

        aroon_up = (period - max_idx) / period * 100
        aroon_down = (period - min_idx) / period * 100

        if aroon_up > 70 and aroon_down < 30:
            signal = 'AROON_STRONG_BULL'
        elif aroon_down > 70 and aroon_up < 30:
            signal = 'AROON_STRONG_BEAR'
        elif aroon_up > aroon_down:
            signal = 'AROON_BULLISH'
        elif aroon_down > aroon_up:
            signal = 'AROON_BEARISH'
        else:
            signal = 'NEUTRAL'

        # Aroon 交叉检测（前一个bar）
        if self.n >= period + 5:
            prev_closes = self.closes[-(period+5):-5]
            prev_max = max(prev_closes)
            prev_min = min(prev_closes)
            prev_max_idx = prev_closes.index(prev_max)
            prev_min_idx = prev_closes.index(prev_min)
            prev_up = (period - prev_max_idx) / period * 100
            prev_down = (period - prev_min_idx) / period * 100
            cross_up = (aroon_up > aroon_down) and (prev_up <= prev_down)
            cross_down = (aroon_down > aroon_up) and (prev_down <= prev_up)
        else:
            cross_up = cross_down = False

        return {
            'aroon_up': aroon_up,
            'aroon_down': aroon_down,
            'signal': signal,
            'cross_up': cross_up,
            'cross_down': cross_down,
        }

    # ── 综合分析 ───────────────────────────────────────
    def analyze(self) -> Dict:
        """
        综合所有指标，返回整体信号
        """
        obv = self.obv()
        mfi = self.mfi()
        cmf = self.cmf()
        vwap = self.vwap_deviation()
        vol_spike = self.volume_spike()
        atr = self.atr_regime()
        adx = self.adx()
        aroon = self.aroon()

        # ── 顶部信号汇总 ─────────────────────────────
        top_signals = []
        div_type = (obv.get('divergence_type') or '')
        if 'BEARISH' in div_type:
            top_signals.append('OBV_BEAR_DIV')
        if mfi.get('overbought'):
            top_signals.append('MFI_OVERBOUGHT')
        if 'DISTRIBUTION' in (cmf.get('signal') or ''):
            top_signals.append('CMF_DIST')
        if vwap.get('signal') in ('EXTREME_OVERPRICED',):
            top_signals.append('VWAP_OVERPRICED')
        if vol_spike.get('signal') == 'VOL_SPIKE_TOP':
            top_signals.append('VOL_SPIKE_TOP')
        if atr.get('regime') == 'HIGH_VOLATILITY' and atr.get('atr_change', 0) > 0.2:
            top_signals.append('HIGH_VOL')

        # ── 底部信号汇总 ─────────────────────────────
        bottom_signals = []
        if 'BULLISH' in div_type:
            bottom_signals.append('OBV_BULL_DIV')
        if mfi.get('oversold'):
            bottom_signals.append('MFI_OVERSOLD')
        if 'ACCUMULATION' in (cmf.get('signal') or ''):
            bottom_signals.append('CMF_ACCUM')
        if cmf.get('cross_up'):
            bottom_signals.append('CMF_CROSS_UP')
        if vwap.get('signal') == 'EXTREME_UNDERPRICED':
            bottom_signals.append('VWAP_UNDERPRICED')
        if vol_spike.get('signal') == 'VOL_SPIKE_BOTTOM':
            bottom_signals.append('VOL_SPIKE_BOTTOM')

        # ── 综合信号判断 ─────────────────────────────
        top_score = len(top_signals)
        bottom_score = len(bottom_signals)

        if top_score >= 2:
            overall = 'LIKELY_TOP'  # 可能顶部
        elif bottom_score >= 2:
            overall = 'LIKELY_BOTTOM'  # 可能底部
        elif top_score == 1 and bottom_score == 0:
            overall = 'SLIGHTLY_OVERBOUGHT'
        elif bottom_score == 1 and top_score == 0:
            overall = 'SLIGHTLY_OVERSOLD'
        else:
            overall = 'NEUTRAL'

        return {
            'overall': overall,
            'top_signals': top_signals,
            'bottom_signals': bottom_signals,
            'top_score': top_score,
            'bottom_score': bottom_score,
            'obv': obv,
            'mfi': mfi,
            'cmf': cmf,
            'vwap': vwap,
            'vol_spike': vol_spike,
            'atr': atr,
            'adx': adx,
            'aroon': aroon,
        }


# 快速测试
if __name__ == '__main__':
    import json
    from pathlib import Path

    klines_dir = Path(__file__).resolve().parent.parent.parent.parent / "TradingAgents" / "中间过程" / "klines"
    ticker = "AAPL"

    def load_bars(ticker):
        path = klines_dir / f"{ticker}_1d.json"
        with open(path) as f:
            data = json.load(f)
        return data.get('data', [])[-100:]

    bars = load_bars(ticker)
    if not bars:
        print(f"No data for {ticker}")
    else:
        va = VolumeAnalyzer(bars)
        r = va.analyze()
        print(f"\n{'='*60}")
        print(f"  {ticker} 量价分析报告")
        print(f"{'='*60}")
        print(f"  综合信号: {r['overall']}")
        print(f"  顶部信号: {r['top_signals']}")
        print(f"  底部信号: {r['bottom_signals']}")
        print(f"  OBV信号: {r['obv']['signal']}")
        print(f"  MFI: {r['mfi']['value']:.1f} ({r['mfi']['signal']})")
        print(f"  CMF: {r['cmf']['value']:+.3f} ({r['cmf']['signal']})")
        print(f"  VWAP偏离: {r['vwap']['pct_from_vwap']:+.1f}% ({r['vwap']['signal']})")
        print(f"  量比: {r['vol_spike']['vol_ratio']:.1f}x ({r['vol_spike']['signal']})")
        print(f"  ATR regime: {r['atr']['regime']} ({r['atr']['signal']})")
        print(f"  ADX: {r['adx']['adx']:.1f} ({r['adx']['signal']}, {r['adx']['trend_dir']})")
        print(f"  Aroon: up={r['aroon']['aroon_up']:.0f} down={r['aroon']['aroon_down']:.0f} ({r['aroon']['signal']})")
