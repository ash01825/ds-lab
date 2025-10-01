import asyncio
import websockets
import json
import time
import random
from zookeeper_mock import ZookeeperMock
from database_mock import DatabaseMock

# --- System State (The Single Source of Truth) ---
STATE = {
    "signals": {"1": "red", "2": "red", "3": "red", "4": "red"},
    "pedestrians": {"1": "green", "2": "green", "3": "green", "4": "green"},
    "timers": {"1-2": 0, "3-4": 0},
    "clock_sync": "SYNCED",
    "critical_section": "none",
    "controllers": {"primary": "active", "backup": "standby"},
    "zookeeper_leader": "primary",
    "database_synced": True,
    "traffic_sensors": {"1-2": "normal", "3-4": "normal"},
    "events": {
        "emergency": {"active": False, "road": None},
        "vip": {"active": False, "road": None},
        "deadlock": {"active": False, "resolved": False},
        "alert": {"active": False, "message": ""}
    },
    "log": [],
    "timestamp": 0
}

# --- System Configuration ---
BASE_GREEN_TIME = 15
HEAVY_TRAFFIC_EXTENSION = 10
YELLOW_TIME = 3
ALL_RED_TIME = 2
TICK_INTERVAL = 1

# --- Global Variables ---
clients = set()
zookeeper = ZookeeperMock(["primary", "backup"])
database = DatabaseMock()
# A lock to prevent race conditions when multiple events are triggered
event_lock = asyncio.Lock()


# --- Helper Functions ---
def get_current_time_str():
    return time.strftime("%H:%M:%S")


def add_log(message):
    """Adds a message to the system log."""
    log_entry = f"[{get_current_time_str()}] {message}"
    STATE["log"].insert(0, log_entry)
    STATE["log"] = STATE["log"][:20]  # Keep only the last 20 entries
    print(log_entry)


# --- Main Simulation Logic ---
async def run_simulation():
    """The main loop that drives the traffic signal simulation."""
    global STATE
    current_phase = "3-4"
    add_log("System Online. Initializing simulation.")
    STATE["timers"]["3-4"] = BASE_GREEN_TIME + YELLOW_TIME

    while True:
        await asyncio.sleep(TICK_INTERVAL)

        async with event_lock:
            STATE["timestamp"] = int(time.time())

            # --- Smart Sensor Simulation ---
            if random.random() < 0.1:  # 10% chance per second to change traffic conditions
                road_to_change = random.choice(["1-2", "3-4"])
                new_condition = random.choice(["normal", "heavy"])
                if STATE["traffic_sensors"][road_to_change] != new_condition:
                    STATE["traffic_sensors"][road_to_change] = new_condition
                    add_log(f"Traffic sensor: Road {road_to_change} traffic is now {new_condition}.")

            # --- Handle Special Events ---
            # If an event is active, it overrides normal signal logic.
            if any(event["active"] for event in STATE["events"].values()):
                database.write_state(STATE)
                await broadcast_state()
                continue

            # --- Normal Signal Logic ---
            if current_phase == "1-2":
                timer_key, other_timer_key = "1-2", "3-4"
                signal_group, other_signal_group = ["1", "2"], ["3", "4"]
            else:
                timer_key, other_timer_key = "3-4", "1-2"
                signal_group, other_signal_group = ["3", "4"], ["1", "2"]

            # Decrement the active timer
            if STATE["timers"][timer_key] > 0:
                STATE["timers"][timer_key] -= 1

            time_left = STATE["timers"][timer_key]

            # State transitions based on timer
            if time_left > YELLOW_TIME:  # Green Phase
                STATE["critical_section"] = timer_key
                for s in signal_group:
                    STATE["signals"][s] = "green"
                    STATE["pedestrians"][s] = "red"
                for s in other_signal_group:
                    STATE["signals"][s] = "red"
                    STATE["pedestrians"][s] = "green"

            elif YELLOW_TIME >= time_left > 0:  # Yellow Phase
                STATE["critical_section"] = "transition"
                for s in signal_group:
                    STATE["signals"][s] = "yellow"
                for s in ["1", "2", "3", "4"]:
                    STATE["pedestrians"][s] = "red"  # All pedestrians stop

            elif time_left == 0:  # Switch Phase
                STATE["critical_section"] = "all-red"
                for s in ["1", "2", "3", "4"]:
                    STATE["signals"][s] = "red"

                await broadcast_state()
                await asyncio.sleep(ALL_RED_TIME)  # All-red safety gap

                # Determine green time for the next phase based on traffic
                green_time = BASE_GREEN_TIME
                if STATE["traffic_sensors"][other_timer_key] == "heavy":
                    green_time += HEAVY_TRAFFIC_EXTENSION
                    add_log(f"Heavy traffic on {other_timer_key}, extending green time.")

                current_phase = other_timer_key
                STATE["timers"][timer_key] = 0
                STATE["timers"][other_timer_key] = green_time + YELLOW_TIME
                add_log(f"Phase changing to {current_phase}. Green time: {green_time}s.")

        database.write_state(STATE)
        await broadcast_state()


# --- Event Simulation Coroutines ---
async def simulate_event(event_name, duration, setup_func, teardown_func):
    """A generic wrapper for handling events to avoid race conditions."""
    async with event_lock:
        if any(e["active"] for e in STATE["events"].values()):
            add_log(f"Cannot trigger '{event_name}': another event is in progress.")
            return

        original_state = database.read_state()

        try:
            add_log(f"--- Event Started: {event_name.upper()} ---")
            await setup_func()
            await broadcast_state()

            await asyncio.sleep(duration)

            add_log(f"--- Event Finished: {event_name.upper()} ---")
            await teardown_func(original_state)

        except Exception as e:
            add_log(f"Error during {event_name} event: {e}")
            await teardown_func(original_state)  # Attempt to restore state on error

    await broadcast_state()


async def simulate_emergency():
    road = random.choice(["1", "2", "3", "4"])

    async def setup():
        STATE["events"]["emergency"] = {"active": True, "road": road}
        for s_id in STATE["signals"]:
            STATE["signals"][s_id] = "red"
            STATE["pedestrians"][s_id] = "red"
        STATE["critical_section"] = "EMERGENCY"

    async def teardown(original_state):
        STATE["events"]["emergency"]["active"] = False
        # Restore signals to their pre-event state. The main loop will then correct them.
        STATE["signals"] = original_state["signals"]

    await simulate_event("emergency", 8, setup, teardown)


async def simulate_vip():
    road = random.choice(["1", "3"])
    vip_pair = "1-2" if road == "1" else "3-4"

    async def setup():
        STATE["events"]["vip"] = {"active": True, "road": vip_pair}
        for s_id in ["1", "2", "3", "4"]:
            STATE["signals"][s_id] = "red" if s_id not in vip_pair.split('-') else "green"
            STATE["pedestrians"][s_id] = "red"
        STATE["critical_section"] = f"VIP-{vip_pair}"

    async def teardown(original_state):
        STATE["events"]["vip"]["active"] = False
        STATE["signals"] = original_state["signals"]

    await simulate_event("vip", 6, setup, teardown)


async def simulate_deadlock():
    async def setup():
        STATE["events"]["deadlock"] = {"active": True, "resolved": False}
        STATE["critical_section"] = "GRIDLOCK"

    async def teardown(original_state):
        add_log("Gridlock resolved by system intervention.")
        STATE["events"]["deadlock"]["resolved"] = True
        await broadcast_state()
        await asyncio.sleep(2)
        STATE["events"]["deadlock"]["active"] = False

    await simulate_event("deadlock", 4, setup, teardown)


async def simulate_failover():
    """Simulates controller failover, doesn't use the generic wrapper."""
    async with event_lock:
        add_log("--- SIMULATING CONTROLLER FAILOVER ---")
        new_leader, failed_leader = zookeeper.simulate_failover()

        if new_leader and failed_leader:
            STATE["zookeeper_leader"] = new_leader
            STATE["controllers"][new_leader] = "active"
            STATE["controllers"][failed_leader] = "failed"
            add_log(f"Controller '{failed_leader}' failed. '{new_leader}' is now active.")

            # New leader restores state from the database
            restored_state = database.read_state()
            if restored_state:
                # We don't restore everything, just critical operational data
                # to avoid overwriting the failover status itself.
                STATE["signals"] = restored_state["signals"]
                STATE["timers"] = restored_state["timers"]
                add_log(f"New leader '{new_leader}' restored state from database.")

            await broadcast_state()
            await asyncio.sleep(5)

            STATE["controllers"][failed_leader] = "standby"
            add_log(f"Controller '{failed_leader}' recovered, now on standby.")

    await broadcast_state()


async def simulate_alert():
    async def setup():
        STATE["events"]["alert"] = {"active": True, "message": "Accident Reported"}

    async def teardown(original_state):
        STATE["events"]["alert"]["active"] = False

    await simulate_event("alert", 10, setup, teardown)


# --- WebSocket Communication ---
async def handle_client_message(websocket, message):
    """Handles incoming messages from the frontend."""
    try:
        data = json.loads(message)
        action = data.get("action")
        add_log(f"Client command received: '{action}'")

        tasks = {
            "trigger_emergency": simulate_emergency,
            "trigger_vip": simulate_vip,
            "trigger_deadlock": simulate_deadlock,
            "trigger_failover": simulate_failover,
            "trigger_alert": simulate_alert,
        }
        if action in tasks:
            asyncio.create_task(tasks[action]())

    except json.JSONDecodeError:
        add_log("Invalid JSON received from a client.")


async def broadcast_state():
    """Sends the current state to all connected clients."""
    if clients:
        message = json.dumps(STATE)
        await asyncio.gather(*[client.send(message) for client in clients])


async def handler(websocket):
    """Handles WebSocket connections."""
    clients.add(websocket)
    add_log(f"Client connected. Total clients: {len(clients)}")
    try:
        await websocket.send(json.dumps(STATE))  # Send initial state
        async for message in websocket:
            await handle_client_message(websocket, message)
    except websockets.exceptions.ConnectionClosed:
        add_log("Client disconnected.")
    finally:
        clients.remove(websocket)


async def main():
    """Main function to start the server and the simulation."""
    asyncio.create_task(run_simulation())
    async with websockets.serve(handler, "localhost", 8765):
        print("\nSmart City Traffic Control Server is RUNNING.")
        print("WebSocket listening on ws://localhost:8765")
        print("Open index.html in your browser to see the simulation.\n")
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer shutting down.")

