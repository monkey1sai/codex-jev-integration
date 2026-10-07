"""Non-network regression: reject remote bindings before filesystem operations."""
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('inventory_safety', Path(__file__).parent / 'payload/jev/inventory.py')
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)


class LocalSkillBindingTests(unittest.TestCase):
    def test_unc_and_device_rejected_before_any_filesystem_read(self):
        with patch.object(Path, 'lstat', side_effect=AssertionError('Filesystem probe forbidden')):
            for binding in ['\\\\untrusted\\share\\SKILL.md', '//untrusted/share/SKILL.md',
                            '\\\\?\\UNC\\untrusted\\share\\SKILL.md', '\\\\.\\C:\\SKILL.md']:
                self.assertEqual(inventory._skill(binding), (False, None, 'NONLOCAL_SKILL_BINDING'))

    @unittest.skipUnless(os.name == 'nt', 'Windows drive check')
    def test_mapped_network_drive_rejected_before_filesystem_read(self):
        with patch('ctypes.windll.kernel32.GetDriveTypeW', return_value=4), \
             patch.object(Path, 'lstat', side_effect=AssertionError('Filesystem probe forbidden')):
            self.assertEqual(inventory._skill('Z:\\assets\\SKILL.md'), (False, None, 'NONLOCAL_SKILL_BINDING'))


if __name__ == '__main__':
    unittest.main()
