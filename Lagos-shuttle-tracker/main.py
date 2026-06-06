import asyncio
import json
import random
import time
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from routes import LAGOS_ROUTES

app = FastAPI()
app.mount("/static", StaticFiles(directory="."), name="static")

# ------------------------------------------------
# 1. Landing page – the new HTML
# ------------------------------------------------
@app.get("/")
async def root():
    return HTMLResponse(Path("index.html").read_text())

# ------------------------------------------------
# 2. API: all routes (name + waypoints)
# ------------------------------------------------
@app.get("/api/routes")
async def get_routes():
    # Return route names and waypoints (just the first & last point is enough for bounds,
    # but we return all for drawing the polyline)
    return [
        {"name": r["name"], "waypoints": r["waypoints"]}
        for r in LAGOS_ROUTES
    ]

# ------------------------------------------------
# 3. WebSocket – unchanged
# ------------------------------------------------
connected_clients = set()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        connected_clients.remove(websocket)
    except Exception:
        connected_clients.discard(websocket)

async def broadcast(data):
    if not connected_clients:
        return
    message = json.dumps(data)
    await asyncio.gather(
        *(client.send_text(message) for client in connected_clients),
        return_exceptions=True
    )

# ------------------------------------------------
# 4. Vehicle simulation – unchanged
# ------------------------------------------------
class Vehicle:
    def __init__(self, vehicle_id, route):
        self.id = vehicle_id
        self.route = route["waypoints"]
        self.route_name = route["name"]
        self.vehicle_type = random.choice(["bus", "car"])
        self.segment_index = random.randint(0, len(self.route) - 2)
        self.progress = random.random()
        self.speed = random.uniform(20, 55) * 0.000005

    def update_position(self, dt):
        self.progress += self.speed * dt * 100
        while self.progress >= 1.0 and self.segment_index < len(self.route) - 1:
            self.progress -= 1.0
            self.segment_index += 1
        if self.segment_index >= len(self.route) - 1:
            self.segment_index = 0
            self.progress = 0.0

    @property
    def position(self):
        p1 = self.route[self.segment_index]
        p2 = self.route[self.segment_index + 1]
        lat = p1[0] + (p2[0] - p1[0]) * self.progress
        lon = p1[1] + (p2[1] - p1[1]) * self.progress
        return lat, lon

    def to_dict(self):
        lat, lon = self.position
        return {
            "id": self.id,
            "type": self.vehicle_type,
            "name": self.route_name,
            "lat": lat,
            "lon": lon,
            "route": self.route_name,   # needed for filtering
            "speed_kmh": round(self.speed / 0.000005, 1)
        }

VEHICLE_COUNT = 60
vehicles = [Vehicle(i, random.choice(LAGOS_ROUTES)) for i in range(VEHICLE_COUNT)]

async def simulator():
    interval = 0.5
    last_time = time.time()
    while True:
        now = time.time()
        dt = now - last_time if last_time else interval
        last_time = now
        for v in vehicles:
            v.update_position(dt)
        data = [v.to_dict() for v in vehicles]
        await broadcast(data)
        await asyncio.sleep(interval)

@app.on_event("startup")
async def startup():
    asyncio.create_task(simulator())

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8765)