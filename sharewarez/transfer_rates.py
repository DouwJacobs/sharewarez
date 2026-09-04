"""Bounded, process-local rate samples keyed by HTTP transfer attempt."""

from collections import OrderedDict, deque
import threading


class TransferRates:
    def __init__(self, window=8.0, capacity=10000):
        self.window = window
        self.capacity = capacity
        self._samples = OrderedDict()
        self._lock = threading.Lock()

    def observe(self, transfer_id, sent, now, last_activity):
        """Return bytes/second, or None until there is a useful sample interval.

        Duplicate viewers cannot shorten the sample window or multiply memory.
        Rates describe server-sent bytes, not confirmed writes to the client disk.
        """
        with self._lock:
            samples = self._samples.setdefault(transfer_id, deque(maxlen=12))
            self._samples.move_to_end(transfer_id)
            while len(self._samples) > self.capacity:
                self._samples.popitem(last=False)
            if samples and (now < samples[-1][0] or sent < samples[-1][1]):
                samples.clear()
            if not samples or now - samples[-1][0] >= 0.9:
                samples.append((now, sent))
            while len(samples) > 2 and samples[1][0] <= now - self.window:
                samples.popleft()
            if now - last_activity >= self.window:
                return 0.0
            if len(samples) < 2 or now - samples[0][0] < 1:
                return None
            # A long gap (hidden page/reconnect) is not a current-speed sample.
            if now - samples[-2][0] > self.window * 2:
                samples.clear()
                samples.append((now, sent))
                return None
            return max(0.0, (sent - samples[0][1]) / (now - samples[0][0]))


transfer_rates = TransferRates()
