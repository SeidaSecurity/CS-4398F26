import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from simulator import Scenario
from install_bridge import install

class BridgeTests(unittest.TestCase):
    def test_bridge_rejects_nonlocal_urls(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bridge'))
        from demo_metrics_adapter import fetch_demo_metrics
        with patch.dict(os.environ, {'CS4398_DEMO_METRICS_URL': 'http://example.com'}):
            self.assertIsNone(fetch_demo_metrics('network','1h'))

    def test_standby_metrics_off_before_push(self):
        with tempfile.TemporaryDirectory() as d:
            s = Scenario(Path(d) / 'missing.json')
            cpu = s.metrics(device=True, device_name='Standby-R4')['cpu'][-1]['value']
            self.assertEqual(cpu,0.0)

if __name__ == '__main__': unittest.main()
