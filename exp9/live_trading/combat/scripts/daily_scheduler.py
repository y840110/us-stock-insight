#!/usr/bin/env python3
"""
每日定时任务调度器
==================
每天 ET 13:25（开盘前）自动重建盘中监控任务链。

依赖：openclaw CLI
用法：
    python3 daily_scheduler.py --date 2026-06-03   # 指定日期（默认今天）
    # 或直接通过 cron 调用：
    # openclaw cron add --name "daily_scheduler" --schedule "cron 25 13 * * 1-5" ...
"""

import json
import subprocess
import sys
import argparse
from datetime import date, datetime, timedelta
import pytz

TZ_ET = pytz.timezone('America/New_York')

# 飞书会话 ID
FEISHU_SESSION_ID = 'oc_c76cd3b3bc91d7f50594ab5a242d73a6'

# 每日盘中推送时间（ET）
# 市场交易时段：09:30 - 16:00 ET
# 每小时一次：10:30, 11:30, 12:30, 13:30, 14:30, 15:30（最后一小时 16:30 超出 RTH）
SCAN_TIMES_ET = [
    (10, 30),  # 10:30 ET = 14:30 UTC
    (11, 30),  # 11:30 ET = 15:30 UTC
    (12, 30),  # 12:30 ET = 16:30 UTC
    (13, 30),  # 13:30 ET = 17:30 UTC
    (14, 30),  # 14:30 ET = 18:30 UTC
    (15, 30),  # 15:30 ET = 19:30 UTC
    # 17:00 ET 收盘总结单独处理，不在这里
]

SCRIPT_CWD = '/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/live_trading/combat'
PYTHON = sys.executable
PYTHONPATH = '/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/model/experts'

INTRADAY_MSG = (
    "请在后台执行以下命令，完成后直接退出（无需回复用户）：\n"
    f"cd {SCRIPT_CWD} && \n"
    f"PYTHONPATH={PYTHONPATH} \n"
    f"{PYTHON} scripts/intraday_monitor.py --auto-update\n"
    "\n"
    "该脚本会自动更新数据、扫描市场、并将结果推送到飞书，无需额外操作。"
)

def et_to_utc(date_obj, hour, minute):
    """将 ET 日期时间转换为 UTC datetime"""
    et_dt = TZ_ET.localize(datetime(date_obj.year, date_obj.month, date_obj.day, hour, minute, 0))
    return et_dt.astimezone(pytz.utc)

def list_existing_jobs():
    """列出所有 intraday_ 开头的 job"""
    r = subprocess.run(
        ['openclaw', 'cron', 'list', '--json'],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        return []
    try:
        data = json.loads(r.stdout)
        return [j for j in data.get('jobs', []) if j['name'].startswith('intraday_')]
    except:
        return []

def delete_job(job_id):
    subprocess.run(
        ['openclaw', 'cron', 'remove', job_id],
        capture_output=True, text=True
    )

def create_job(name, at_utc, message):
    """创建单个 cron job"""
    at_str = at_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
    cmd = [
        'openclaw', 'cron', 'add',
        '--name', name,
        '--at', at_str,
        '--session', 'isolated',
        '--delete-after-run',
        '--message', message,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0, r.stdout + r.stderr

def setup_daily_jobs(target_date: date):
    """为指定日期创建全部盘中任务链"""
    print(f"\n📅 为 {target_date} (ET) 创建盘中任务链...")

    # 先删除旧任务
    old = list_existing_jobs()
    if old:
        print(f"   删除旧任务 {len(old)} 个...")
        for j in old:
            delete_job(j['id'])

    created = []
    for hour, minute in SCAN_TIMES_ET:
        utc_dt = et_to_utc(target_date, hour, minute)
        name = f"intraday_{target_date.strftime('%Y-%m-%d')}_{hour:02d}{minute:02d}_et"
        ok, out = create_job(name, utc_dt, INTRADAY_MSG)
        status = '✅' if ok else f'❌ {out[:80]}'
        print(f"   {status} {name} → {utc_dt.strftime('%H:%M UTC')}")
        created.append((name, ok))

    print(f"\n✅ 完成：{sum(1 for _, ok in created if ok)}/{len(created)} 个任务已创建")
    return created

# ── CLI ─────────────────────────────────────────────────────
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='每日盘中任务调度器')
    parser.add_argument('--date', default=None, help='目标日期 YYYY-MM-DD（默认今天 ET）')
    parser.add_argument('--dry-run', action='store_true', help='只显示，不实际创建')
    args = parser.parse_args()

    if args.date:
        target = datetime.strptime(args.date, '%Y-%m-%d').date()
    else:
        now_et = datetime.now(TZ_ET)
        target = now_et.date()

    # US 节假日（2026）
    US_HOLIDAYS_2026 = {
        date(2026, 1, 1): "New Year's Day",
        date(2026, 1, 19): "MLK Day",
        date(2026, 2, 16): "Presidents' Day",
        date(2026, 4, 3): "Good Friday",
        date(2026, 5, 25): "Memorial Day",
        date(2026, 6, 19): "Juneteenth",
        date(2026, 7, 3): "Independence Day (observed)",
        date(2026, 9, 7): "Labor Day",
        date(2026, 11, 26): "Thanksgiving",
        date(2026, 12, 25): "Christmas",
    }

    if target.weekday() >= 5:
        print(f"⏭️  {target} 是周末，跳过")
    elif target in US_HOLIDAYS_2026:
        print(f"⏭️  {target} 是假日（{US_HOLIDAYS_2026[target]}），跳过")
    elif args.dry_run:
        print(f"[Dry Run] 为 {target} 将创建 {len(SCAN_TIMES_ET)} 个任务:")
        for hour, minute in SCAN_TIMES_ET:
            utc_dt = et_to_utc(target, hour, minute)
            print(f"   {target} {hour:02d}:{minute:02d} ET = {utc_dt.strftime('%H:%M UTC')}: intraday_{target}_{hour:02d}{minute:02d}_et")
    else:
        setup_daily_jobs(target)
