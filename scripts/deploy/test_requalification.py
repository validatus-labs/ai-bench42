"""Native drift handover: preserve history, explicit pins and real proof gates."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('requalify', HERE / 'requalify-existing.py')
controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller)


class RequalificationTests(unittest.TestCase):
    def data(self):
        root = '/private/runtime'
        return dict(existing_runtime=root, destination_runtime=root + '/tools/new-host',
                    browser_runtime=root + '/tools/new-browser', controller_source=root + '/build/source',
                    source_root='/private/source', browser_sha256='b'*64, node_sha256='n'*64,
                    module_seal_sha256='m'*64)

    def installer(self):
        return SimpleNamespace(load_profile=Mock(return_value={}), inventory=Mock(return_value={
            'browser_sha256': 'b'*64, 'node_sha256': 'n'*64,
            'module_seal': {'sha256': 'm'*64}, 'packages': {'@playwright/mcp': 'fixed'}}), install=Mock())

    def invoke(self, data, action, installer):
        with patch.object(controller.adoption, 'identity'), patch.object(controller.adoption, 'module', return_value=installer):
            return controller.run(data, action, Path('/private/proof'))

    def test_inspect_never_installs_or_publishes(self):
        installer = self.installer()
        with patch.object(controller.adoption, 'adopt') as adopt:
            self.assertEqual(self.invoke(self.data(), 'inspect', installer)['status'], 'PINS_MATCH')
            installer.install.assert_not_called(); adopt.assert_not_called()

    def test_wrong_native_pin_stops_before_any_mutation(self):
        installer = self.installer(); data = self.data(); data['node_sha256'] = '0'*64
        with patch.object(controller.adoption, 'adopt') as adopt:
            with self.assertRaisesRegex(RuntimeError, 'Observed native pin differs'):
                self.invoke(data, 'apply', installer)
            installer.install.assert_not_called(); adopt.assert_not_called()

    def test_historical_browser_directory_cannot_be_replaced(self):
        data = self.data(); data['browser_runtime'] = data['existing_runtime'] + '/tools/playwright-tool'
        installer = self.installer()
        with self.assertRaisesRegex(RuntimeError, 'Preserve the historical launcher'):
            self.invoke(data, 'apply', installer)
        installer.inventory.assert_not_called(); installer.install.assert_not_called()

    def test_historical_registry_cannot_be_replaced(self):
        data = self.data(); data['destination_runtime'] = data['existing_runtime'] + '/tools/ai-bench42-host'
        with self.assertRaisesRegex(RuntimeError, 'Preserve the historical whole-stack'):
            self.invoke(data, 'apply', self.installer())

    def test_failed_browser_proof_cannot_return_success(self):
        installer = self.installer()
        with patch.object(controller.adoption, 'adopt', side_effect=RuntimeError('real browser failed')):
            with self.assertRaisesRegex(RuntimeError, 'real browser failed'):
                self.invoke(self.data(), 'apply', installer)
            installer.install.assert_called_once()

    def test_verify_does_not_rerun_install_or_browser(self):
        installer = self.installer()
        with patch.object(controller.adoption, 'check') as check, patch.object(controller.adoption, 'adopt') as adopt:
            self.assertEqual(self.invoke(self.data(), 'verify', installer)['status'], 'VERIFIED')
            check.assert_called_once(); adopt.assert_not_called(); installer.install.assert_not_called()


if __name__ == '__main__':
    unittest.main()
