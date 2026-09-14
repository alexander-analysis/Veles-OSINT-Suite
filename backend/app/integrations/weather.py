"""OpenWeatherMap current conditions at a position (environmental context; optional key)."""

import httpx

from app.config import settings


async def fetch_weather(lat: float, lon: float) -> dict | None:
    key = settings.key("OPENWEATHERMAP_API_KEY")
    if not key:
        return None
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"lat": lat, "lon": lon, "appid": key, "units": "metric"},
        )
        if response.status_code != 200:
            return None
        data = response.json()
    return {
        "conditions": (data.get("weather") or [{}])[0].get("description"),
        "temperature_c": data.get("main", {}).get("temp"),
        "wind_speed_ms": data.get("wind", {}).get("speed"),
        "wind_deg": data.get("wind", {}).get("deg"),
        "visibility_m": data.get("visibility"),
    }
