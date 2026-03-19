"""Weather API tools for MCP server using Open-Meteo."""

from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import urlopen

from proxi.observability.logging import get_logger

logger = get_logger(__name__)


def _weather_description(code: int) -> str:
    """Map Open-Meteo weather codes to short descriptions."""
    descriptions = {
        0: "Clear sky",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Depositing rime fog",
        51: "Light drizzle",
        53: "Moderate drizzle",
        55: "Dense drizzle",
        56: "Light freezing drizzle",
        57: "Dense freezing drizzle",
        61: "Slight rain",
        63: "Moderate rain",
        65: "Heavy rain",
        66: "Light freezing rain",
        67: "Heavy freezing rain",
        71: "Slight snow fall",
        73: "Moderate snow fall",
        75: "Heavy snow fall",
        77: "Snow grains",
        80: "Slight rain showers",
        81: "Moderate rain showers",
        82: "Violent rain showers",
        85: "Slight snow showers",
        86: "Heavy snow showers",
        95: "Thunderstorm",
        96: "Thunderstorm with slight hail",
        99: "Thunderstorm with heavy hail",
    }
    return descriptions.get(code, "Unknown")


class WeatherTools:
    """Tools for interacting with Open-Meteo weather APIs."""

    GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
    FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

    def _http_get_json(self, base_url: str, params: dict[str, str | int]) -> dict:
        """Execute a GET request and parse JSON response."""
        url = f"{base_url}?{urlencode(params)}"
        with urlopen(url, timeout=15) as response:  # nosec B310
            payload = response.read().decode("utf-8")
        return json.loads(payload)

    def _resolve_location(self, location: str) -> dict:
        """Resolve a location name to coordinates and place metadata."""
        location_name = location.strip()
        if not location_name:
            raise ValueError("location cannot be empty")

        data = self._http_get_json(
            self.GEOCODING_URL,
            {
                "name": location_name,
                "count": 1,
                "language": "en",
                "format": "json",
            },
        )
        results = data.get("results", [])
        if not results:
            raise ValueError(f"No location found for '{location_name}'")
        return results[0]

    async def get_current_weather(self, location: str, unit: str = "celsius") -> dict:
        """Get current weather for a location name."""
        try:
            normalized_unit = unit.lower().strip()
            if normalized_unit not in ("celsius", "fahrenheit"):
                return {"error": "unit must be either 'celsius' or 'fahrenheit'"}

            place = self._resolve_location(location)
            forecast = self._http_get_json(
                self.FORECAST_URL,
                {
                    "latitude": place["latitude"],
                    "longitude": place["longitude"],
                    "current": (
                        "temperature_2m,apparent_temperature,relative_humidity_2m,"
                        "weather_code,wind_speed_10m"
                    ),
                    "temperature_unit": normalized_unit,
                    "wind_speed_unit": "kmh",
                    "timezone": "auto",
                },
            )

            current = forecast.get("current", {})
            weather_code = int(current.get("weather_code", -1))
            return {
                "location": {
                    "name": place.get("name"),
                    "country": place.get("country"),
                    "admin1": place.get("admin1"),
                    "latitude": place.get("latitude"),
                    "longitude": place.get("longitude"),
                    "timezone": forecast.get("timezone"),
                },
                "current": {
                    "time": current.get("time"),
                    "temperature": current.get("temperature_2m"),
                    "apparent_temperature": current.get("apparent_temperature"),
                    "relative_humidity": current.get("relative_humidity_2m"),
                    "wind_speed_kmh": current.get("wind_speed_10m"),
                    "weather_code": weather_code,
                    "weather": _weather_description(weather_code),
                    "unit": normalized_unit,
                },
            }
        except Exception as e:
            logger.error("weather_current_error", error=str(e), location=location)
            return {"error": str(e)}

    async def get_forecast(self, location: str, days: int = 3, unit: str = "celsius") -> dict:
        """Get multi-day weather forecast for a location name."""
        try:
            normalized_unit = unit.lower().strip()
            if normalized_unit not in ("celsius", "fahrenheit"):
                return {"error": "unit must be either 'celsius' or 'fahrenheit'"}

            forecast_days = max(1, min(int(days), 7))

            place = self._resolve_location(location)
            forecast = self._http_get_json(
                self.FORECAST_URL,
                {
                    "latitude": place["latitude"],
                    "longitude": place["longitude"],
                    "daily": (
                        "weather_code,temperature_2m_max,temperature_2m_min,"
                        "precipitation_probability_max"
                    ),
                    "forecast_days": forecast_days,
                    "temperature_unit": normalized_unit,
                    "timezone": "auto",
                },
            )

            daily = forecast.get("daily", {})
            times = daily.get("time", [])
            codes = daily.get("weather_code", [])
            max_temps = daily.get("temperature_2m_max", [])
            min_temps = daily.get("temperature_2m_min", [])
            precip_probs = daily.get("precipitation_probability_max", [])

            days_out = []
            for idx, date in enumerate(times):
                weather_code = int(codes[idx]) if idx < len(codes) else -1
                days_out.append(
                    {
                        "date": date,
                        "weather_code": weather_code,
                        "weather": _weather_description(weather_code),
                        "temp_max": max_temps[idx] if idx < len(max_temps) else None,
                        "temp_min": min_temps[idx] if idx < len(min_temps) else None,
                        "precipitation_probability_max": (
                            precip_probs[idx] if idx < len(precip_probs) else None
                        ),
                        "unit": normalized_unit,
                    }
                )

            return {
                "location": {
                    "name": place.get("name"),
                    "country": place.get("country"),
                    "admin1": place.get("admin1"),
                    "latitude": place.get("latitude"),
                    "longitude": place.get("longitude"),
                    "timezone": forecast.get("timezone"),
                },
                "forecast_days": days_out,
                "count": len(days_out),
            }
        except Exception as e:
            logger.error("weather_forecast_error", error=str(e), location=location)
            return {"error": str(e)}
