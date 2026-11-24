import json
import tempfile
import time
import unittest
from pathlib import Path
from simulator import Scenario

class TestScenario(unittest.TestCase):
    def test_traffic_spike_and_ssh_standby_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder) / 'router.json'
            state.write_text(json.dumps({'interfaces': {'GigabitEthernet0/1': {'shutdown': True}}}))
            demo = Scenario(state, step=0)
            now = time.time()
            demo.last_tick = now - 1
            for n in range(8):
                t = now + n * 1.5
                demo.recent.extend(t - i / 24.0 for i in range(96))
                demo.tick(t)
            peak = demo.cpu
            self.assertGreater(peak, 80)
            state.write_text(json.dumps({'interfaces': {'GigabitEthernet0/1': {'shutdown': False}}}))
            for n in range(8, 16):
                t = now + n * 1.5
                demo.recent.extend(t - i / 24.0 for i in range(96))
                demo.tick(t)
            self.assertTrue(demo.standby())
            self.assertLess(demo.cpu, peak)
            self.assertIn('cpu_avg', demo.metrics())
            self.assertIn('cpu', demo.metrics(device=True))

    def test_empty_standby_file_is_off(self):
        with tempfile.TemporaryDirectory() as folder:
            demo = Scenario(Path(folder) / 'missing.json')
            self.assertFalse(demo.standby())

if __name__ == '__main__':
    unittest.main()
