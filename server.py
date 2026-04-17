# app.py
import asyncio
from fastapi import FastAPI, WebSocket
from mavsdk import System

app = FastAPI()
drone = System()


# -------------------------------
# CONNECT
# -------------------------------
@app.on_event("startup")
async def connect():
    await drone.connect("/dev/ttyAMA0")

    async for state in drone.core.connection_state():
        if state.is_connected:
            print("Connected")
            break

    await drone.action.arm()
    print("Armed")


# -------------------------------
# SET MOTOR PWM (DIRECT)
# -------------------------------
async def set_servo(channel: int, pwm: int):
    """
    channel: 1–8
    pwm: 1000–2000
    """
    await drone.mavlink.send_command_long(
        command=183,  # MAV_CMD_DO_SET_SERVO
        param1=channel,
        param2=pwm,
        param3=0, param4=0,
        param5=0, param6=0, param7=0
    )


@app.post("/set")
async def set_motors(values: list[float]):
    """
    Input: [0.0 – 1.0] per motor
    Maps to PWM 1000–2000
    """

    values = (values + [0.0]*4)[:4]

    for i, v in enumerate(values):
        pwm = int(1000 + v * 1000)
        await set_servo(i+1, pwm)

    return {"status": "ok", "input": values}


# -------------------------------
# REAL-TIME TELEMETRY
# -------------------------------
@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()

    async for battery in drone.telemetry.battery():
        await websocket.send_json({
            "voltage": battery.voltage_v,
            "current": battery.current_battery_a,
        })
