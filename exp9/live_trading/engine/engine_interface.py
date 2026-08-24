#!/usr/bin/env python3
"""
engine_interface.py 鈥?闈㈠悜瀹炵洏鐨勭ǔ瀹?API
==========================================

鏈�鏂囦欢鏄� combat 妯″潡涓庡紩鎿庝箣闂寸殑鍞�涓�鎺ュ彛銆?寮曟搸鍐呴儴瀹炵幇鍙�闅忔椂鍗囩骇锛屾帴鍙ｅ嚱鏁扮�惧悕淇濇寔涓嶅彉銆?
鎺ュ彛璁捐�″師鍒欙�?  - evaluate_entry / evaluate_exit 鏄�绾�璁＄畻鍑芥暟锛堟棤鍓�浣滅敤锛氫笉鍐欐枃浠躲�佷笉鎿嶄綔鐜伴噾锛?  - 杩斿洖缁撴瀯鍙�鎵╁睍锛屼絾瀛楁�靛悕/鍚�涔変笉鍙�
  - 鍙傛暟鏈夐粯璁ゅ�硷紝璋冪敤鏂瑰彲鐪佺暐

鍏稿瀷鐢ㄦ硶锛坈ombat 妯″潡锛夛細
    from engine_interface import evaluate_entry, evaluate_exit
    signal = evaluate_entry('AAPL', daily_bars, spy_bars, h1_bars)
    if signal['signal'] == 'BUY_NOW':
        print(f"涔板叆 {signal['ticker']} @ {signal['entry']}")
"""

import sys
import json
from pathlib import Path

# 鈹�鈹� 璺�寰勯厤缃� 鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�
# 鍚戜笂4绾у埌杈?workspace/锛屽啀杩涘叆缇庤偂鎶曡祫娲炲療鍒嗘瀽
# engine/(0) 鈫?live_trading/(1) 鈫?exp9/(2) 鈫?缇庤偂鎶曡祫娲炲療鍒嗘瀽/(3) 鈫?workspace/(4)
PROJ = Path(__file__).resolve().parent
for _ in range(4):
    PROJ = PROJ.parent
PROJ = PROJ / '美股投资洞察分析'
MODEL = PROJ / 'exp9' / 'model' / 'experts'
sys.path.insert(0, str(MODEL))

from p_buy_filter_v2 import BuyFilterEngine, _atr as _atr_daily


# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?# 宸ュ叿鍑芥暟锛堜笌 engine_h3_4_1.py 鍏辩敤锛?# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?
def _atr_1h(bars: list, entry_idx: int, current_idx: int, period: int = 14) -> float:
    """璁＄畻 1h ATR锛堜粠鍏ュ満idx鍒板綋鍓峣dx绐楀彛鍐咃級"""
    if current_idx <= entry_idx or current_idx < 1:
        return 0.0
    trs = []
    for i in range(entry_idx, min(current_idx + 1, len(bars))):
        if i == 0:
            continue
        h = float(bars[i]["high"]); l = float(bars[i]["low"])
        pc = float(bars[i - 1]["close"])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs[-period:]) / min(period, len(trs)) if trs else 0.0


def _atr_from_daily(bars: list, period: int = 14) -> float:
    """璁＄畻鏃ョ嚎 ATR"""
    return _atr_daily(bars, period)


# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?# 鏍稿績鎺ュ彛鍑芥暟
# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?
def evaluate_entry(
    ticker: str,
    daily_bars: list,
    spy_bars: list,
    h1_bars: list,
    *,
    atr_mult: float = 1.5,
    target_mult: float = 3.0,
) -> dict:
    """
    璇勪及鍗曞彧鑲＄エ鐨勪拱鍏ヤ俊鍙凤紙绾�璁＄畻锛屼笉鎿嶄綔浠撲�?鐜伴噾锛?
    鍙傛暟锛?        ticker       鑲＄エ浠ｇ爜
        daily_bars   鏃ョ嚎 K 绾匡紙list of dict锛宒ate/open/high/low/close/volume锛?        spy_bars     SPY 鏃ョ嚎锛堝競鍦虹幆澧冨弬鑰冿級
        h1_bars      灏忔椂 K 绾匡紙鏈�杩戯紝list of dict锛?        atr_mult     姝㈡崯 ATR 鍊嶆暟锛堥粯璁?1.5锛?        target_mult  鐩�鏍� ATR 鍊嶆暟锛堥粯璁?3.0锛?
    杩斿洖锛?        {
            'signal':         'BUY_NOW' | 'BUY_WATCH' | 'NO_SIGNAL',
            'stage':          'STAGE_3' | 'STAGE_4' | None,
            'action':         'NOW' | 'WATCH' | None,
            'grade':          'A' | 'B' | 'C' | None,
            'entry':          float,        # 杩涘満浠?            'stop':           float,        # 姝㈡崯浠?            'target':         float,        # 鐩�鏍囦�?            'rr':             float,        # 椋庨櫓鏀剁泭姣?            'l1_regime':      str,         # BULL / BEAR / NEUTRAL
            'pullback_tier':  int,         # 1=EMA50 2=瓒嬪娍绾?3=瀹介�氶亾
            'volume_confirm': bool,
            'atr':            float,       # 鏃ョ嚎 ATR
            'last_price':     float,       # 鏈�鏂颁环
            'last_bar_time':  str,         # 鏈�鏂?bar 鏃堕棿
            'error':          None | str,
        }
    """
    result = {
        'signal': 'NO_SIGNAL',
        'stage': None,
        'action': None,
        'grade': None,
        'entry': None,
        'stop': None,
        'target': None,
        'rr': None,
        'l1_regime': 'UNKNOWN',
        'pullback_tier': 0,
        'volume_confirm': False,
        'atr': 0.0,
        'last_price': None,
        'last_bar_time': None,
        'error': None,
    }

    if len(daily_bars) < 60:
        result['error'] = '鏁版嵁涓嶈冻'
        return result

    # 鏈�鏂版湁鏁堟棩绾?bar
    valid_daily = [b for b in daily_bars if float(b.get('volume', 0)) > 0]
    if not valid_daily:
        result['error'] = 'No valid daily data'
        return result

    last_d = valid_daily[-1]
    result['last_price'] = float(last_d['close'])
    result['last_bar_time'] = last_d.get('date', '')
    result['atr'] = round(_atr_from_daily(daily_bars), 4)

    try:
        engine = BuyFilterEngine(ticker, daily_bars, spy_bars)
        sig = engine.run(bars_1h=h1_bars[-100:] if h1_bars else None)

        layers = sig.get('layers', {})
        l1 = layers.get('L1', {})
        l3 = layers.get('L3', {})
        l4 = layers.get('L4', {})
        l5 = layers.get('L5', {})

        stage = sig.get('stage')
        stage_info_action = sig.get('stage_info', {}).get('action')
        grade = sig.get('grade', '?')

        result['stage'] = stage
        result['action'] = stage_info_action
        result['grade'] = grade
        result['l1_regime'] = l1.get('regime', 'UNKNOWN')
        result['pullback_tier'] = l3.get('pullback_tier', 0)
        result['volume_confirm'] = l4.get('volume_confirm', False)

        # 鍙�鏈� STAGE_4 + NOW + BULL + RR >= 1.5 鈫?BUY_NOW
        if (stage == 'STAGE_4'
                and stage_info_action == 'NOW'
                and result['l1_regime'] == 'BULL'
                and not result.get('error')):
            rr_details = l5.get('details', {})
            if rr_details:
                result['entry'] = rr_details.get('entry')
                result['stop'] = rr_details.get('stop')
                result['target'] = rr_details.get('target')
                rr = l5.get('rr_ratio')
                result['rr'] = rr
                result['signal'] = 'BUY_NOW'

        # STAGE_3 + WATCH + BULL + 鍥炶俯 >= 1绾?鈫?BUY_WATCH
        elif (stage == 'STAGE_3'
              and stage_info_action == 'WATCH'
              and result['l1_regime'] == 'BULL'
              and result['pullback_tier'] >= 1):
            rr_details = l5.get('details', {})
            if rr_details:
                result['entry'] = rr_details.get('entry')
                result['stop'] = rr_details.get('stop')
                result['target'] = rr_details.get('target')
                rr = l5.get('rr_ratio')
                result['rr'] = rr
                
                result['signal'] = 'BUY_WATCH'

    except Exception as e:
        result['error'] = str(e)

    return result


def evaluate_exit(
    position: dict,
    h1_bars: list,
    entry_h1_idx: int,
    current_h1_idx: int,
    *,
    atr_mult: float = 1.5,
    atr_trailing_mult: float = 4.0,
    min_hold: int = 5,
    target_mult: float = 3.0,
) -> dict:
    """
    璇勪及鎸佷粨鏄�鍚﹂渶瑕佸嚭鍦猴紙绾�璁＄畻锛屽畬鍏ㄥ�归綈 engine_h3_4_1.py 鐨?_track_1h锛?
    鍙傛暟锛?        position          鎸佷粨瀛楀吀锛堣�佷笅鏂瑰瓧娈佃�存槑锛?        h1_bars           灏忔椂 K 绾?list锛堝畬鏁达紝dateime/open/high/low/close/volume锛?        entry_h1_idx      鍏ュ満瀵瑰簲鐨?h1 bar 绱㈠紩锛堝湪 h1_bars 涓�鐨勪綅缃�锛?        current_h1_idx    褰撳墠璇勪及鐨?h1 bar 绱㈠紩
        atr_mult          姝㈡崯 ATR 鍊嶆暟锛堥粯璁?1.5锛?        atr_trailing_mult ATR trailing姝㈢泩鍊嶆暟锛堥粯璁?4.0锛?        min_hold          鏈�灏忔寔浠撳皬鏃舵暟锛堥粯璁?5锛?        target_mult       鐩�鏍� ATR 鍊嶆暟锛堥粯璁?3.0锛?
    position 蹇呰�佸瓧娈碉�?        ticker        str   鑲＄エ浠ｇ爜
        entry_price   float 鍏ュ満浠锋牸
        atr           float 鏃ョ嚎 ATR锛堢敤浜庤�＄畻鐩�鏍囧拰姝㈡崯锛?        stop_loss     float 鍒濆�嬫�㈡崯浠?        target        float 鏃ョ嚎鐩�鏍囦�?        peak_price    float Lot1瑙﹁揪鍚庣殑宄板�硷紙鍒濆��=entry_price锛?
    position 鍙�閫夊瓧娈碉紙鏈夐粯璁ゅ�硷級锛?        lot1_done     bool  Lot1鐩�鏍囨槸鍚﹀凡瑙﹁揪锛堥粯璁� False锛?        lot2_stop     float 褰撳墠杩借釜姝㈡崯浠凤紙榛樿�� = stop_loss锛?        atr_1h        float 1h ATR锛堝�傛棤鍒欒嚜鍔ㄨ�＄畻锛?
    杩斿洖锛?        {
            'action':     'HOLD'
                        | 'STOP_LOSS'
                        | 'LOT1_HIT'
                        | 'LOT2_ATR_TRAILING'
                        | 'LOT2_BACK_TO_ENTRY',
            'exit_price': float | None,   # 闇�瑕佸嚭鍦虹殑浠锋牸锛堣Е鍙戜俊鍙凤級
            'message':    str,            # 鍙�璇绘弿杩�
            'details': {
                'atr_1h':      float,
                'trailing_stop': float,
                'peak':         float,
                'hold_h1':     int,
                'profit_pct':   float,
                'atr':          float,
            }
        }

    瑙勫垯锛堝畬鍏ㄥ�归�?engine_h3_4_1.py _track_1h锛夛細
        1. 姝㈡崯锛氫环鏍?<= lot2_stop 鈫?STOP_LOSS
        2. Lot1鐩�鏍囷細鏈�瑙﹁揪 + 浠锋牸 >= target + 鎸佷粨>=2h 鈫?LOT1_HIT锛堜繚鏈�姝㈡崯锛�
        3. Lot2锛坙ot1_done=True 涓?hold>=min_hold锛夛細
           a. 璺屽洖 entry_price 鈫?LOT2_BACK_TO_ENTRY锛堜繚鏈�锛�
           b. close < peak - atr_trailing_mult*atr_1h 鈫?LOT2_ATR_TRAILING
    """
    ticker = position.get('ticker', '?')
    entry_price = position['entry_price']
    atr = position.get('atr', 0.0)
    daily_target = position.get('target', entry_price + target_mult * atr)
    stop_loss = position.get('stop_loss', entry_price - atr_mult * atr)
    peak_price = position.get('peak_price', entry_price)
    lot1_done = position.get('lot1_done', False)
    lot2_stop = position.get('lot2_stop', stop_loss)

    if current_h1_idx <= entry_h1_idx:
        hold_h1 = 0
    else:
        hold_h1 = current_h1_idx - entry_h1_idx

    if not h1_bars or current_h1_idx >= len(h1_bars):
        return {
            'action': 'HOLD',
            'exit_price': None,
            'message' : 'No 1h data or index out of bounds',
            'details': {
                'atr_1h': 0.0, 'trailing_stop': 0.0,
                'peak': entry_price, 'hold_h1': hold_h1,
                'profit_pct': 0.0, 'atr': atr,
            }
        }

    cur = h1_bars[current_h1_idx]
    cur_open  = float(cur['open'])
    cur_close = float(cur['close'])
    cur_high  = float(cur['high'])
    cur_low   = float(cur['low'])

    profit_pct = (cur_close - entry_price) / entry_price * 100

    # 鈹�鈹� 姝㈡崯妫�鏌?鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�
    # Gap down 寮�鐩樹綆浜庢�㈡崯浠�
    if cur_open < lot2_stop:
        return {
            'action': 'STOP_LOSS',
            'exit_price': round(lot2_stop, 2),
            'message': f'Stop loss triggered (open {cur_open:.2f} <= stop {lot2_stop:.2f})',
            'details': {
                'atr_1h': 0.0, 'trailing_stop': lot2_stop,
                'peak': peak_price, 'hold_h1': hold_h1,
                'profit_pct': profit_pct, 'atr': atr,
            }
        }
    # 鐩樹腑浠锋牸璺岀牬姝㈡崯
    if cur_low <= lot2_stop:
        return {
            'action': 'STOP_LOSS',
            'exit_price': round(lot2_stop, 2),
            'message': f'Stop loss triggered (low {cur_low:.2f} <= stop {lot2_stop:.2f})',
            'details': {
                'atr_1h': 0.0, 'trailing_stop': lot2_stop,
                'peak': peak_price, 'hold_h1': hold_h1,
                'profit_pct': profit_pct, 'atr': atr,
            }
        }

    # 鈹�鈹� Lot1 鐩�鏍囪Е杈撅紙涓嶆�㈡崯锛屾�㈡崯涓婄Щ淇濇湰锛夆攢鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�
    if not lot1_done:
        hit_target = any(
            float(h1_bars[j]["high"]) >= daily_target
            for j in range(entry_h1_idx + 1, current_h1_idx + 1)
        )
        if hit_target and hold_h1 >= 2:
            return {
                'action': 'LOT1_HIT',
                'exit_price': round(daily_target, 2),
                'message': (
                    f'Lot1 target {daily_target:.2f} hit -> trail stop to entry {entry_price:.2f}'
                    f' | 鐜颁环 {cur_close:.2f}'
                ),
                'details': {
                    'atr_1h': 0.0, 'trailing_stop': entry_price,
                    'peak': cur_high, 'hold_h1': hold_h1,
                    'profit_pct': profit_pct, 'atr': atr,
                }
            }

    # 鈹�鈹� Lot2锛氭寔浠?>= min_hold 鍚庯紝ATR trailing / 璺屽洖鍏ュ満 鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�
    if lot1_done and hold_h1 >= min_hold:
        # 璁＄畻 ATR_1h
        atr_1h = position.get('atr_1h')
        if atr_1h is None:
            atr_1h = _atr_1h(h1_bars, entry_h1_idx, current_h1_idx)

        # 杩借釜宄板�硷紙鍙�涓婄Щ涓嶄笅绉伙�?
        peak = max(peak_price, cur_high)

        # ATR trailing stop
        trailing_stop = peak - atr_trailing_mult * atr_1h

# 鏉′欢B锛氳穼鍥?entry_price锛堝叏鍑猴紝淇濇湰锛?
        if cur_low <= entry_price:
            return {
                'action': 'LOT2_BACK_TO_ENTRY',
                'exit_price': round(entry_price, 2),
                'message': (
                    f'Lot2 back to entry {entry_price:.2f} (break even)'
                    f' | 宄板�?{peak:.2f} | ATR_1h {atr_1h:.4f}'
                ),
                'details': {
                    'atr_1h': round(atr_1h, 4),
                    'trailing_stop': round(trailing_stop, 2),
                    'peak': round(peak, 2),
                    'hold_h1': hold_h1,
                    'profit_pct': round(profit_pct, 2),
                    'atr': atr,
                }
            }

        # 鏉′欢A锛欰TR trailing 瑙﹀彂
        if cur_close < trailing_stop:
            return {
                'action': 'LOT2_ATR_TRAILING',
                'exit_price': round(trailing_stop, 2),
                'message': (
                    f'Lot2 ATR璺熻釜姝㈢泩瑙﹀彂 {trailing_stop:.2f}'
                    f'(peak {peak:.2f} - {atr_trailing_mult}*ATR_1h {atr_1h:.4f})'
                ),
                'details': {
                    'atr_1h': round(atr_1h, 4),
                    'trailing_stop': round(trailing_stop, 2),
                    'peak': round(peak, 2),
                    'hold_h1': hold_h1,
                    'profit_pct': round(profit_pct, 2),
                    'atr': atr,
                }
            }

        # 未触发，返回当前追踪状态
        return {
            'action': 'HOLD',
            'exit_price': None,
            'message': (
                f'鎸佷粨涓?{hold_h1}h | 鐜颁环 {cur_close:.2f} | '
                f'宄板�?{peak:.2f} | ATR_1h {atr_1h:.4f} | 璺熻釜姝㈡崯 {trailing_stop:.2f}'
            ),
            'details': {
                'atr_1h': round(atr_1h, 4),
                'trailing_stop': round(trailing_stop, 2),
                'peak': round(peak, 2),
                'hold_h1': hold_h1,
                'profit_pct': round(profit_pct, 2),
                'atr': atr,
            }
        }

    # 鈹�鈹� 鎸佷粨涓�锛堟湭婊¤冻鍑哄満鏉′欢锛夆攢鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�鈹�
    return {
        'action': 'HOLD',
        'exit_price': None,
        'message': (
            f'鎸佷粨涓?{hold_h1}h | 鐜颁环 {cur_close:.2f} | '
            f'鍏ュ満 {entry_price:.2f} | 姝㈡崯 {lot2_stop:.2f}'
        ),
        'details': {
            'atr_1h': 0.0, 'trailing_stop': lot2_stop,
            'peak': peak_price, 'hold_h1': hold_h1,
            'profit_pct': round(profit_pct, 2), 'atr': atr,
        }
    }


# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?# 杈呭姪鍑芥暟锛堢粰 alerts_scanner.py 浣跨敤锛?# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?
def load_daily_bars(ticker: str, lookback: int = 300) -> list:
    """Load daily K-line."""
    klines_dir = PROJ / 'TradingAgents' / '中间过程' / 'klines'
    path = klines_dir / f'{ticker}_1d.json'
    if not path.exists():
        return []
    try:
        with open(path) as f:
            d = json.load(f)
        bars = d.get('data', [])
        return bars[-lookback:] if bars else []
    except Exception:
        return []


def load_h1_bars(ticker: str, lookback: int = 2000) -> list:
    """Load hourly K-line (US RTH 9:30-15:30 ET)"""
    klines_dir = PROJ / 'TradingAgents' / '中间过程' / 'klines'
    path = klines_dir / f'{ticker}_1h.json'
    if not path.exists():
        return []
    try:
        with open(path) as f:
            d = json.load(f)
        bars = d.get('data', [])
        if not bars:
            return []
        bars = bars[-lookback:]
        # 缇庤偂 RTH: 9:30-15:30 ET
        filtered = []
        for b in bars:
            dt = b.get('datetime', '')
            if len(dt) >= 18:
                try:
                    hour = int(dt[11:13]); minute = int(dt[14:16])
                    if (hour == 9 and minute >= 30) or (10 <= hour <= 14) or (hour == 15 and minute <= 30):
                        filtered.append(b)
                except ValueError:
                    continue
        return filtered
    except Exception:
        return []


def load_spy_bars(lookback: int = 400) -> list:
    """鍔犺浇 SPY 鏃ョ嚎"""
    return load_daily_bars('SPY', lookback)


def find_h1_entry_idx(h1_bars: list, entry_date: str) -> int:
    """Find first RTH bar index for entry_date."""

    if not h1_bars:
        return 0
    for i, b in enumerate(h1_bars):
        if b.get('datetime', '')[:10] == entry_date[:10]:
            return i
    return max(0, len(h1_bars) - 20)


def entry_params_from_daily(daily_bars: list, entry_price: float,
                            atr_mult: float = 1.5,
                            target_mult: float = 3.0) -> dict:
    """Estimate entry params (stop/ATR/target) from daily bars."""


    atr = _atr_from_daily(daily_bars)
    if atr == 0:
        h = float(daily_bars[-1]['high']); l = float(daily_bars[-1]['low'])
        atr = (h - l) / 4
    return {
        'atr': round(atr, 4),
        'stop_loss': round(entry_price - atr_mult * atr, 2),
        'target': round(entry_price + target_mult * atr, 2),
    }
