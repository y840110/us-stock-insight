#!/usr/bin/env python3
"""
逐K分析引擎封装 - 完全复刻h3-4-1回测逻辑
"""
import sys
from pathlib import Path

# 设置正确的路径
BASE = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析')
sys.path.insert(0, str(BASE / 'exp9' / 'model' / 'experts'))
sys.path.insert(0, str(BASE / 'exp9' / 'live_trading' / 'engine'))

from p_buy_filter_v2 import BuyFilterEngine
from engine_h3_4_1 import _atr as _atr_daily


class EngineWrapper:
    def __init__(self):
        self.signal_count = 0
        # 策略参数（与回测保持一致）
        self.atr_mult = 1.5
        self.atr_trailing_mult = 3.0
        self.min_hold = 5
        self.target_mult = 3.0
        # pending状态（回测引擎核心机制）
        self.pending = {}

    def evaluate(self, ticker, daily_bars, spy_bars, h1_bars, daily_idx):
        """
        完全复刻回测引擎的入场逻辑
        :param daily_idx: 当前日线索引
        """
        if not daily_bars or len(daily_bars) < 50:
            return {"signal": "NO_SIGNAL"}

        if not spy_bars or len(spy_bars) < 50:
            return {"signal": "NO_SIGNAL"}

        # 检查是否有下一根日线（用于获取次日开盘价）
        if daily_idx + 1 >= len(daily_bars):
            return {"signal": "NO_SIGNAL"}

        try:
            # 获取pending状态（回测引擎核心机制）
            prev_entry = self.pending.get(ticker)
            
            # 创建 BuyFilterEngine 实例（与回测完全一致）
            buy_filter = BuyFilterEngine(ticker=ticker, bars=daily_bars[:daily_idx+1], spy_bars=spy_bars[:daily_idx+1])
            # 传入daily_entry_price参数（关键！）
            sig = buy_filter.run(bars_1h=None, daily_entry_price=prev_entry)

            # 提取信号信息（完全复刻回测逻辑）
            stage = sig.get('stage', 'STAGE_F')
            stage_info = sig.get('stage_info', {})
            action = stage_info.get('action', 'NO_ACTION')
            l1_reg = sig['layers'].get('L1', {}).get('regime', 'BEAR')
            l5_veto = sig['layers'].get('L5', {}).get('veto', False)
            grade = sig.get('grade', 'D')
            l5 = sig['layers'].get('L5', {})
            rr = l5.get('details', {})

            # 更新pending状态（回测引擎核心机制 - 无论是否入场都要更新）
            if stage == 'STAGE_4' and action == 'NOW':
                self.pending[ticker] = None
            elif stage == 'STAGE_1' and not l5_veto:
                self.pending[ticker] = float(daily_bars[daily_idx]['high'])

            # 回测引擎的入场条件（完全一致）
            # 1. L1不是熊市
            if l1_reg == 'BEAR':
                return {'signal': 'NO_SIGNAL', 'reason': 'L1_BEAR', 'stage': stage, 'action': action}
            
            # 2. L5没有否决
            if l5_veto:
                return {'signal': 'NO_SIGNAL', 'reason': 'L5_VETO', 'stage': stage, 'action': action}
            
            # 3. STAGE_4 + NOW
            if stage != 'STAGE_4' or action != 'NOW':
                return {'signal': 'NO_SIGNAL', 'reason': f'STAGE_{stage}_ACTION_{action}', 'stage': stage, 'action': action}

            # 4. 次日开盘价作为入场价（回测核心逻辑）
            entry_price = float(daily_bars[daily_idx + 1]['open'])
            if entry_price <= 0:
                return {'signal': 'NO_SIGNAL', 'reason': 'INVALID_ENTRY_PRICE'}

            # 5. 计算ATR和止损目标（与回测完全一致）
            atr = rr.get('atr', 0) or _atr_daily(daily_bars[:daily_idx+1])
            if atr <= 0:
                return {'signal': 'NO_SIGNAL', 'reason': 'ATR_ZERO'}

            # 使用rr中的stop_loss（关键！回测引擎优先使用rr中的止损价）
            stop_loss = rr.get('stop_loss') or (entry_price - self.atr_mult * atr)
            target = rr.get('mm_target') or (entry_price + self.target_mult * atr)

            self.signal_count += 1

            return {
                'signal': 'BUY_NOW',
                'action': 'NOW',
                'stage': stage,
                'grade': grade,
                'entry': entry_price,
                'stop': stop_loss,
                'target': target,
                'rr': rr.get('rr_ratio', 3.0),
                'atr': atr,
                'l1_regime': l1_reg,
                'entry_date': daily_bars[daily_idx + 1].get('date', ''),
                'bars_at_entry': daily_idx,
            }

        except Exception as e:
            print(f"Engine evaluate error: {e}")
            import traceback
            traceback.print_exc()
            return {'signal': 'NO_SIGNAL'}

    def evaluate_position(self, position_info, h1_bars, entry_h1_idx, current_h1_idx):
        """
        完全复刻h3-4-1回测引擎的出场逻辑
        h3-4-1：Lot1目标触达不卖出，止损上移保本；Lot2用ATR追踪止损
        """
        if not position_info or not position_info.get("position"):
            return {"action": "HOLD"}

        try:
            entry_price = position_info.get('entry_price', 0)
            stop_loss = position_info.get('stop_loss', 0)
            target = position_info.get('target', 0.0)
            atr = position_info.get('atr', 0.0)
            lot1_done = position_info.get('lot1_done', False)
            lot2_stop = position_info.get('lot2_stop', stop_loss)
            peak_price = position_info.get('peak_price', entry_price)

            if not h1_bars or current_h1_idx >= len(h1_bars):
                return {'action': 'HOLD'}

            # 获取当前小时K数据
            current_bar = h1_bars[current_h1_idx]
            cur_open = float(current_bar.get('open', 0))
            cur_close = float(current_bar.get('close', 0))
            cur_high = float(current_bar.get('high', 0))
            cur_low = float(current_bar.get('low', 0))

            hold_h1 = current_h1_idx - entry_h1_idx if current_h1_idx > entry_h1_idx else 0

            # 更新峰值
            if cur_high > peak_price:
                peak_price = cur_high

            # ── 止损（完全复刻回测逻辑）────────────────
            # 开盘价跌破止损
            if cur_open < lot2_stop:
                return {
                    'action': 'STOP_OUT',
                    'exit_price': round(lot2_stop, 2),
                    'reason': 'STOP_LOSS',
                    'peak_price': peak_price,
                }
            # 盘中价格跌破止损
            if cur_low <= lot2_stop:
                return {
                    'action': 'STOP_OUT',
                    'exit_price': round(lot2_stop, 2),
                    'reason': 'STOP_LOSS',
                    'peak_price': peak_price,
                }

            # ── Lot1：日线目标触达 → 不卖出，止损上移至入场价（保本）──
            if not lot1_done:
                # 检查是否触达目标（从入场到当前的所有小时K）
                hit_target = any(
                    float(h1_bars[j]["high"]) >= target
                    for j in range(entry_h1_idx + 1, current_h1_idx + 1)
                )
                if hit_target and hold_h1 >= 2:
                    # h3-4-1核心改动：不卖出lot1，只把止损上移至entry_price
                    return {
                        'action': 'LOT1_HIT',  # 特殊信号：Lot1目标触达
                        'exit_price': round(target, 2),
                        'reason': 'LOT1_TARGET',
                        'peak_price': cur_high,
                        'new_stop': entry_price,  # 止损上移至入场价
                    }

            # ── Lot2：ATR自适应trailing OR 跌回entry_price → 全出 ──
            if lot1_done and hold_h1 >= self.min_hold:
                # 计算ATR_1h（从入场到当前）
                atr_1h = position_info.get('atr_1h')
                if atr_1h is None:
                    trs = []
                    for i in range(entry_h1_idx, min(current_h1_idx + 1, len(h1_bars))):
                        if i == 0:
                            continue
                        h = float(h1_bars[i]["high"])
                        l = float(h1_bars[i]["low"])
                        pc = float(h1_bars[i-1]["close"])
                        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
                    atr_1h = sum(trs[-14:]) / min(14, len(trs)) if trs else 0.0
                    position_info['atr_1h'] = atr_1h

                peak = position_info.get('peak_price', entry_price)
                # 追踪峰值（只上移不下移）
                if cur_high > peak:
                    peak = cur_high

                # 条件B：价格跌回entry_price（全出，保本）
                if cur_low <= entry_price:
                    return {
                        'action': 'EXIT',
                        'exit_price': entry_price,
                        'reason': 'LOT2_BACK_TO_ENTRY',
                        'peak_price': peak,
                    }

                # 条件A：ATR trailing 止盈
                trailing_stop = peak - self.atr_trailing_mult * atr_1h
                if cur_close < trailing_stop:
                    return {
                        'action': 'EXIT',
                        'exit_price': round(trailing_stop, 2),
                        'reason': 'LOT2_ATR_TRAILING',
                        'peak_price': peak,
                    }

            # 继续持有
            return {
                'action': 'HOLD',
                'current_stop': lot2_stop,
                'trailing_stop': peak_price - self.atr_trailing_mult * (position_info.get('atr_1h') or atr),
                'peak_price': peak_price,
                'hold_h1': hold_h1,
            }

        except Exception as e:
            print(f"Exit evaluation error: {e}")
            import traceback
            traceback.print_exc()
            return {'action': 'HOLD'}

    def reset_pending(self):
        """重置pending状态（用于新的股票分析）"""
        self.pending = {}