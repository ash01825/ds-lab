import json
import time


class DatabaseMock:
    """
    A mock implementation of a shared, consistent database.
    It stores the system state as a single JSON-like document. In a real system,
    this could be a distributed database like etcd, Consul, or a replicated SQL server.
    """

    def __init__(self):
        self._state = {}
        self._last_write_time = None
        print(f"[{self._get_time()}] [Database Mock] Shared database initialized.")

    def _get_time(self):
        return time.strftime("%H:%M:%S")

    def write_state(self, new_state):
        """
        Writes the current state to the database. In a real system, this would
        involve network calls, replication, and consensus protocols.
        """
        # Use deep copy to prevent mutation issues
        self._state = json.loads(json.dumps(new_state))
        self._last_write_time = time.time()
        # print(f"[{self._get_time()}] [Database Mock] State written to database.")
        return True

    def read_state(self):
        """

        Reads the last known state from the database. This is critical for a
        new leader to take over after a failover.
        """
        if not self._state:
            print(f"[{self._get_time()}] [Database Mock] Read failed: No state available.")
            return None

        # print(f"[{self._get_time()}] [Database Mock] State read from database.")
        # Use deep copy to ensure the internal state isn't accidentally changed
        return json.loads(json.dumps(self._state))

