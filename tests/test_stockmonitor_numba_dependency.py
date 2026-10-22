#!/usr/bin/env python3
"""
Regression test: com.nse.stockmonitor (main.py) needs numba, and says so when it is missing.

pandas_ta imports numba at module load, but requirements.txt never declared it, so a venv
built from requirements died at `from stock_monitor import StockMonitor` with a traceback
five frames deep inside pandas_ta (deployed launchd-stderr.log, 2026-05-19). numba was then
hand-installed into the deployed venv; nothing in the repo recorded that.

The contract pinned here:
  * requirements.txt declares numba, at the version the deployed venv runs.
  * main.py, started without numba, exits non-zero with a message naming the install step,
    before importing stock_monitor.

Runs offline: the subprocess blocks numba via sys.modules and stops at the guard, so no
DB, broker, Telegram or credentials are touched.
"""

import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestNumbaDependency(unittest.TestCase):

    def test_requirements_declare_numba(self):
        with open(os.path.join(ROOT, 'requirements.txt')) as f:
            pins = [line.split('#')[0].strip() for line in f]
        self.assertIn('numba==0.65.1', pins)

    def test_main_fails_clearly_without_numba(self):
        blocker = ("import sys, runpy; sys.modules['numba'] = None; "
                   "runpy.run_path('main.py', run_name='__main__')")
        proc = subprocess.run([sys.executable, '-c', blocker], cwd=ROOT,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn('numba is not importable', proc.stderr)
        self.assertIn('pip install numba==0.65.1', proc.stderr)
        self.assertNotIn('Traceback', proc.stderr)


if __name__ == '__main__':
    unittest.main()
