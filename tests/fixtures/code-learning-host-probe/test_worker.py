"""CancelableWorkerの利用者から観測できる契約だけを検査する。"""

import unittest

from worker import CancelableWorker


class CancelableWorkerContract(unittest.TestCase):
    def test_cancelled_work_does_not_publish_a_late_result(self):
        worker = CancelableWorker()
        complete = worker.start()

        worker.cancel()
        complete("late result")

        self.assertIsNone(worker.result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
