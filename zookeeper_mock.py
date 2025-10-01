import time
import random


class ZookeeperMock:
    """
    A mock implementation of a distributed coordination service like ZooKeeper.
    Its primary role here is to manage leader election for the controllers.
    """

    def __init__(self, nodes):
        self.nodes = list(nodes)
        self.leader = None
        self._elect_leader()
        print(f"[{self._get_time()}] [ZooKeeper Mock] Initial leader elected: {self.leader}")

    def _get_time(self):
        return time.strftime("%H:%M:%S")

    def _elect_leader(self):
        """Simulates the leader election process."""
        if self.nodes:
            self.leader = random.choice(self.nodes)

    def get_leader(self):
        """Returns the current leader."""
        return self.leader

    def simulate_failover(self):
        """
        Simulates the current leader failing.
        A new leader is elected from the remaining nodes.
        """
        if not self.leader:
            print(f"[{self._get_time()}] [ZooKeeper Mock] No leader to fail.")
            return None, None

        failed_leader = self.leader
        print(f"[{self._get_time()}] [ZooKeeper Mock] Leader '{failed_leader}' has failed!")

        # Remove the failed leader from the list of active nodes
        remaining_nodes = [node for node in self.nodes if node != failed_leader]

        if not remaining_nodes:
            print(f"[{self._get_time()}] [ZooKeeper Mock] No nodes left to elect a new leader.")
            self.leader = None
            return None, failed_leader

        # Elect a new leader from the rest
        self.leader = random.choice(remaining_nodes)
        print(f"[{self._get_time()}] [ZooKeeper Mock] New leader elected: {self.leader}")

        return self.leader, failed_leader

