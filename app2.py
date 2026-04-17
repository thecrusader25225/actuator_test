import asyncio
from fastapi import FastAPI, WebSocket
from mavsdk import System
from pymavlink import mavutil
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # for testing
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- CONFIG ----------------
PWM_MIN = 1100
PWM_MAX = 1900
MOTOR_COUNT = 4

# MAVSDK (telemetry + params)
drone = System()

# pymavlink (raw motor control)
mav = mavutil.mavlink_connection('udp:127.0.0.1:14552')


# ---------------- PWM MAPPING ----------------
def to_pwm(v: float) -> int:
    v = max(0.0, min(1.0, v))
    return int(PWM_MIN + v * (PWM_MAX - PWM_MIN))


# ---------------- SET SERVO ----------------
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
    print(f"Channel {channel} → PWM {pwm}")


# ---------------- STARTUP ----------------
@app.on_event("startup")
async def startup():
    print("Connecting MAVSDK...")
    await drone.connect(system_address="udpin://127.0.0.1:14551")

    async for state in drone.core.connection_state():
        if state.is_connected:
            print("MAVSDK Connected")
            break

    # pymavlink heartbeat (CRITICAL)
    print("Waiting for MAVLink heartbeat...")
    mav.wait_heartbeat()
    print(f"Heartbeat OK (sys={mav.target_system})")

    # ---- disable checks + extend disarm ----
    await drone.param.set_param_int("ARMING_CHECK", 0)
    await drone.param.set_param_int("DISARM_DELAY", 60)


@app.post("/init")
async def defaults():
     # ---- restore motors ----
    print("Restoring motor functions...")
    await drone.param.set_param_int("SERVO1_FUNCTION", 33)
    await drone.param.set_param_int("SERVO2_FUNCTION", 34)
    await drone.param.set_param_int("SERVO3_FUNCTION", 35)
    await drone.param.set_param_int("SERVO4_FUNCTION", 36)

    await asyncio.sleep(1)

    # ---- arm ----
    print("Arming...")
    await drone.action.arm()
    await asyncio.sleep(2)

    # ---- take control ----
    print("Switching to direct PWM control...")
    await drone.param.set_param_int("SERVO1_FUNCTION", 0)
    await drone.param.set_param_int("SERVO2_FUNCTION", 0)
    await drone.param.set_param_int("SERVO3_FUNCTION", 0)
    await drone.param.set_param_int("SERVO4_FUNCTION", 0)

    await asyncio.sleep(1)

    # ---- ESC init ----
    print("Initializing ESC (1100)...")
    for i in range(MOTOR_COUNT):
        await set_servo(i + 1, PWM_MIN)

    await asyncio.sleep(2)

    print("SYSTEM READY")


# ---------------- SET MOTORS ----------------
@app.post("/set")
async def set_motors(values: list[float]):
    values = (values + [0.0]*MOTOR_COUNT)[:MOTOR_COUNT]

    for i, v in enumerate(values):
        pwm = to_pwm(v)
        await set_servo(i + 1, pwm)

    return {"status": "ok", "input": values}


# ---------------- KILL SWITCH ----------------
@app.post("/kill")
async def kill():
    for i in range(MOTOR_COUNT):
        await set_servo(i + 1, PWM_MIN)

    return {"status": "killed"}


# ---------------- TELEMETRY ----------------
@app.websocket("/ws")
async def ws(websocket: WebSocket):
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
