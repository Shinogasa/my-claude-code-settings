"""実ホストの調査課題に使う小さな非同期完了fixture。"""


class CancelableWorker:
    def __init__(self):
        self.result = None
        self._current = None

    def start(self):
        ticket = object()
        self._current = ticket

        def complete(value):
            self._publish(ticket, value)

        return complete

    def cancel(self):
        self._current = None

    def _publish(self, ticket, value):
        self.result = value
