#!/usr/bin/env python3
"""CDO: ProcessPoolExecutor with 4 workers fetching Yahoo Finance K-lines via Chrome CDP"""

import json
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

TICKERS = ["IONQ", "NET", "ZS", "SOXX", "ROBO"]
INTERVALS = ["1d", "1wk"]
WORKER = "/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/中间过程/klines/fetch_worker.py"
WORKERS_MAX = 4

def run_one(args):
    ticker, interval = args
    cmd = [sys.executable, WORKER, ticker, interval]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        output = result.stdout.strip()
        # parse RESULT: line
        for line in output.splitlines():
            if line.startswith("RESULT:"):
                return json.loads(line[7:])
        return {"key": f"{ticker}_{interval}", "ok": False, "msg": f"No RESULT line. stderr: {result.stderr[:200]}"}
    except subprocess.TimeoutExpired:
        return {"key": f"{ticker}_{interval}", "ok": False, "msg": "Timeout 60s"}
    except Exception as e:
        return {"key": f"{ticker}_{interval}", "ok": False, "msg": str(e)}


def main():
    tasks = [(t, i) for t in TICKERS for i in INTERVALS]
    results = []

    with ProcessPoolExecutor(max_workers=WORKERS_MAX) as executor:
        futures = {executor.submit(run_one, t): t for t in tasks}
        for future in as_completed(futures):
            results.append(future.result())

    ok_list = [r for r in results if r["ok"]]
    fail_list = [r for r in results if not r["ok"]]

    print("=== 成功 ===")
    for r in ok_list:
        print(f"  {r['key']} ✓  {r['msg']}")

    print("\n=== 失败 ===")
    for r in fail_list:
        print(f"  {r['key']} ✗  {r['msg']}")


if __name__ == "__main__":
    main()
