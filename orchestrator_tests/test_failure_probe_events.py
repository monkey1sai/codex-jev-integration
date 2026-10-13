"""Keep the zero-provider emitter consistent with current failure policy."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from orchestrator.worker_failures import WorkerFailureMonitor
from tools.worker_failure_probe import emit


class FailureProbeEventsTests(unittest.TestCase):
    def test_ordinary_probe_preserves_failure_and_proves_exact_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / '.tmp').mkdir()
            (root / 'artifact').mkdir()
            output = io.StringIO()
            with patch('sys.stdout', output), patch('tools.worker_failure_probe.time.sleep'):
                self.assertEqual(emit('ordinary', root), 0)
            events = [json.loads(line) for line in output.getvalue().splitlines()]
            commands = [e['item'] for e in events if e.get('item', {}).get('type') == 'command_execution']
            self.assertEqual([c['exit_code'] for c in commands], [127, 0])
            self.assertEqual(commands[0]['command'], commands[1]['command'])
            monitor = WorkerFailureMonitor(root / 'monitor', {'attempt': 'synthetic'}, 2, lambda _: None)
            monitor.feed(output.getvalue().encode())
            self.assertFalse(monitor.finish()['stopped'])
            self.assertEqual(monitor.count, 1)


if __name__ == '__main__':
    unittest.main()
