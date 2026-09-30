"""localhost権限不足を個々のruntimeテストの実行前に報告する。"""
import io
import socket
import unittest
from unittest.mock import patch

from tests import test_codex_model_switch_runtime as runtime


class LocalhostPreflightTests(unittest.TestCase):
    def test_permission_denied_reports_one_class_error_without_skip(self):
        """bind拒否なら全メソッドを試さず、復旧手順付きで失敗する。"""
        class PermissionProbe(runtime.CodexModelSwitchRuntimeTests):
            # CLI未導入でも、CLI起動より前の権限検査を検証する。
            __unittest_skip__ = False

        suite = unittest.defaultTestLoader.loadTestsFromTestCase(PermissionProbe)
        with patch.object(socket.socket, "bind", side_effect=PermissionError(1, "Operation not permitted")):
            result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.testsRun, 0)
        self.assertEqual(result.skipped, [])
        self.assertFalse(result.wasSuccessful())
        self.assertIn("localhost の待受が許可されていない実行環境", result.errors[0][1])
        self.assertIn("127.0.0.1", result.errors[0][1])
        self.assertIn("README", result.errors[0][1])


if __name__ == "__main__":
    unittest.main()
