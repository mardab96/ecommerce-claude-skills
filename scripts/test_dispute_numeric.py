import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

script = Path(__file__).parent/'dispute_rate.py'

class NumericTests(unittest.TestCase):
    def run_case(self, amount='10', volume='2026-01=100'):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory)/'synthetic.csv'
            fixture.write_text('amount,reason,transaction_date\n'+amount+',not received,2026-01-01\n', encoding='utf-8')
            return subprocess.run([sys.executable, str(script), str(fixture), '--orders-per-month', volume, '--json'], capture_output=True, text=True, timeout=10)

    def test_amounts_rejected(self):
        for amount in ('', 'bad', 'NaN', 'Infinity', '1e309'):
            with self.subTest(amount=amount):
                self.assertEqual(self.run_case(amount=amount).returncode, 2)

    def test_volumes_rejected(self):
        for volume in ('2026-01=-100', '2026-01=0', '2026-01=NaN', '2026-01=Infinity',
                       '2026-01=1.5', '2026-13=100', 'bad', '2026-01=100,2026-01=200'):
            with self.subTest(volume=volume):
                self.assertEqual(self.run_case(volume=volume).returncode, 2)

    def test_valid_rate(self):
        result = self.run_case()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)['by_month']['2026-01']['rate_pct'], 1)

    def test_missing_volume_stays_unknown(self):
        result = self.run_case(volume='')
        self.assertEqual(result.returncode, 0)
        self.assertIsNone(json.loads(result.stdout)['by_month']['2026-01']['rate_pct'])

    def test_sale_month_differs_from_filing_month(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory)/'synthetic.csv'
            fixture.write_text('Amount,Reason,Transaction date,Filed date\n100,Fraud,2026-01-15,2026-03-02\n100,Not received,2026-01-20,2026-03-04\n', encoding='utf-8')
            result = subprocess.run([sys.executable, str(script), str(fixture), '--orders-per-month', '2026-01=1000', '--json'], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(set(payload['by_month']), {'2026-01'})
            self.assertEqual(payload['by_month']['2026-01']['rate_pct'], .2)

if __name__ == '__main__':
    unittest.main()
