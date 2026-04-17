import asyncio
from fastapi import FastAPI, WebSocket
from mavsdk import System

app = FastAPI()
drone = System()

# -------------------------------
# CONFIG
# -------------------------------
PWM_MIN = 1100
PWM_MAX = 1900
MOTOR_COUNT = 4


# -------------------------------
# HELPER: PWM mapping
# -------------------------------
def to_pwm(v: float) -> int:
    """
    v: 0.0 → 1.0
    maps to 1100–1900
    """
    v = max(0.0, min(1.0, v))
    return int(PWM_MIN + v * (PWM_MAX - PWM_MIN))


# -------------------------------
# HELPER: MAVLINK SERVO COMMAND
# -------------------------------
from pymavlink import mavutil

# connect once (same UDP port or another endpoint)
mav = mavutil.mavlink_connection('udp:127.0.0.1:14552')


async def set_servo(channel: int, pwm: int):
    mav.mav.command_long_send(
        mav.target_system,
        mav.target_component,
        mavutil.mavlink.MAV_CMD_DO_SET_SERVO,
        0,
        channel,
        pwm,
        0, 0, 0, 0, 0
    )



# -------------------------------
# SET TEST MODE PARAMS
# -------------------------------
async def set_test_mode():
    print("Setting TEST mode params...")

    await drone.param.set_param_int("SERVO1_FUNCTION", 0)
    await drone.param.set_param_int("SERVO2_FUNCTION", 0)
    await drone.param.set_param_int("SERVO3_FUNCTION", 0)
    await drone.param.set_param_int("SERVO4_FUNCTION", 0)

    # Optional safety bypass (depends on your setup)
    #await drone.param.set_param_int("BRD_SAFETYENABLE", 0)
    await drone.param.set_param_int("ARMING_CHECK", 0)


# -------------------------------
# SAFE INIT
# -------------------------------
async def init_motors():
    print("Initializing motors to SAFE state...")

    for i in range(MOTOR_COUNT):
        await set_servo(i + 1, PWM_MIN)

    # allow ESCs to initialize
    await asyncio.sleep(2)


# -------------------------------
# STARTUP
# -------------------------------
@app.on_event("startup")
async def startup():
    print("Connecting to Pixhawk...")

    await drone.connect("udpin://127.0.0.1:14551")

    async for state in drone.core.connection_state():
        if state.is_connected:
            print("Connected to Pixhawk")
            break

    # Apply TEST MODE (temporary override)
    await set_test_mode()

    # Give time for params to apply
    await asyncio.sleep(1)

    # Initialize motors safely
    await init_motors()

    print("System READY")


# -------------------------------
# SET ACTUATORS
# -------------------------------
@app.post("/set")
async def set_motors(values: list[float]):
    """
    Input: [0.0–1.0 per motor]
    Example: [0.2, 0.2, 0.2, 0.2]
    """

    values = (values + [0.0]*MOTOR_COUNT)[:MOTOR_COUNT]

    for i, v in enumerate(values):
        pwm = to_pwm(v)
        await set_servo(i + 1, pwm)
        print(f"Channel {i+1} → PWM {pwm}")
    return {
        "status": "ok",
        "input": values
    }


# -------------------------------
# KILL SWITCH
# -------------------------------
@app.post("/kill")
async def kill():
    for i in range(MOTOR_COUNT):
        await set_servo(i + 1, PWM_MIN)

    return {"status": "killed"}


# -------------------------------
# REAL-TIME TELEMETRY (WebSocket)
# -------------------------------
@app.websocket("/ws")
async def telemetry_ws(websocket: WebSocket):
    await websocket.accept()

    try:
        async for battery in drone.telemetry.battery():
            await websocket.send_json({
                "voltage": battery.voltage_v,
                "current": battery.current_battery_a,
                "remaining": battery.remaining_percent
            })

    except Exception as e:
        print("WebSocket closed:", e)
