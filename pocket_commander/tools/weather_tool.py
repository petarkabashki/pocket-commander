import asyncio
import requests # For making HTTP requests to weather API
from geopy.geocoders import Nominatim # For converting location name to coordinates
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
from typing import Optional
import logging

# Import the @tool decorator
from pocket_commander.tools.decorators import tool

logger = logging.getLogger(__name__)

@tool(name="get_current_weather") # Explicit name for clarity
async def get_weather(location: str) -> str:
    """Gets the current weather for a given location using Open-Meteo API.

    Args:
        location (str): The city and state, or just city name (e.g., "San Francisco, CA", "London").
                        This is a required parameter.
    
    Returns:
        str: A string describing the weather conditions or an error message.
    """
    logger.info(f"Attempting to get weather for location: {location}")
    
    geolocator = Nominatim(user_agent="pocket_commander_get_weather/1.0") # Updated user_agent
    lat: Optional[float] = None
    lon: Optional[float] = None

    try:
        location_data = await asyncio.to_thread(geolocator.geocode, location, timeout=10)
        if location_data:
            lat = location_data.latitude
            lon = location_data.longitude
            logger.info(f"Geocoded '{location}' to Lat: {lat}, Lon: {lon}")
        else:
            logger.warning(f"Could not geocode location: {location}")
            return f"Could not find location: {location}. Please provide a valid location."
    except GeocoderTimedOut:
        logger.error(f"Geocoding timed out for location: {location}")
        return f"Geocoding service timed out for {location}. Please try again."
    except GeocoderUnavailable:
        logger.error(f"Geocoding service unavailable for location: {location}")
        return f"Geocoding service is currently unavailable. Please try again later."
    except Exception as e:
        logger.error(f"An unexpected error occurred during geocoding for {location}: {e}", exc_info=True)
        return f"An error occurred while trying to find coordinates for {location}."

    if lat is None or lon is None:
        return f"Could not determine coordinates for {location}."

    weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,weather_code,wind_speed_10m&temperature_unit=celsius&wind_speed_unit=kmh"

    try:
        response = await asyncio.to_thread(requests.get, weather_url, timeout=10)
        response.raise_for_status()
        data = response.json()
        logger.debug(f"Weather API response for {location}: {data}")

        if "current" in data and "temperature_2m" in data["current"] and "weather_code" in data["current"]:
            temp = data["current"]["temperature_2m"]
            weather_code = data["current"]["weather_code"]
            wind_speed = data["current"].get("wind_speed_10m", "N/A")

            weather_description_map = {
                0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
                45: "Fog", 48: "Depositing rime fog",
                51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
                56: "Light freezing drizzle", 57: "Dense freezing drizzle",
                61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
                66: "Light freezing rain", 67: "Heavy freezing rain",
                71: "Slight snow fall", 73: "Moderate snow fall", 75: "Heavy snow fall",
                77: "Snow grains",
                80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
                85: "Slight snow showers", 86: "Heavy snow showers",
                95: "Thunderstorm: Slight or agentrate",
                96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail"
            }
            weather_description = weather_description_map.get(weather_code, f"Weather code {weather_code}")
            
            return f"The weather in {location} is {weather_description} with a temperature of {temp}°C and wind speed of {wind_speed} km/h."
        else:
            logger.warning(f"Unexpected API response structure for {location}: {data}")
            return f"Could not retrieve detailed weather data for {location} at this time."

    except requests.exceptions.Timeout:
        logger.error(f"Weather API request timed out for {location}")
        return f"Weather service request timed out for {location}. Please try again."
    except requests.exceptions.HTTPError as http_err:
        logger.error(f"HTTP error occurred while fetching weather for {location}: {http_err}", exc_info=True)
        return f"Could not fetch weather for {location} (HTTP Error: {http_err.response.status_code})."
    except requests.exceptions.RequestException as req_err:
        logger.error(f"Network error occurred while fetching weather for {location}: {req_err}", exc_info=True)
        return f"Network error fetching weather for {location}. Please check your connection."
    except Exception as e:
        logger.error(f"An unexpected error occurred while fetching weather for {location}: {e}", exc_info=True)
        return f"An error occurred while fetching weather data for {location}."