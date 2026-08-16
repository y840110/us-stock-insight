"""
SPY HMM 预测策略 — 入口脚本
整合了 fetcher / factors / hmm_model / backtester

用法:
  python3 run.py        # 完整流程（抓数据 → 因子 → 训练 → 回测）
  python3 run.py --fetch # 仅抓数据
  python3 run.py --hmm   # 仅训练 HMM
  python3 run.py --bt    # 仅回测
"""
import sys, subprocess

BASE = __file__.parent

def run_step(name, script):
    print(f'\n{"="*50}')
    print(f'  {name}')
    print(f'{"="*50}')
    result = subprocess.run(['python3', script], cwd=BASE, capture_output=False)
    if result.returncode != 0:
        print(f'❌ {name} 失败')
        sys.exit(1)
    print(f'✅ {name} 完成')

def main():
    step = sys.argv[1] if len(sys.argv) > 1 else 'all'

    steps = {
        '--fetch': [('数据获取',        'fetcher.py')],
        '--hmm':  [('因子计算',        'factors.py'),
                   ('HMM 训练与评估',  'hmm_model.py')],
        '--bt':   [('策略回测',        'backtester.py')],
    }

    if step == 'all':
        todo = [
            ('数据获取',        'fetcher.py'),
            ('因子计算',        'factors.py'),
            ('HMM 训练与评估',  'hmm_model.py'),
            ('策略回测',        'backtester.py'),
        ]
    elif step in steps:
        todo = steps[step]
    else:
        print(f'用法: python3 run.py [--fetch|--hmm|--bt]')
        sys.exit(1)

    for name, script in todo:
        run_step(name, script)

    if step == 'all':
        print(f'\n{"="*50}')
        print('  完整流程结束')
        print(f'  模型: {BASE / "models" / "hmm_spy_v2.joblib"}')
        print(f'  报告: {BASE / "results"}')
        print(f'{"="*50}')

if __name__ == '__main__':
    main()
