import asyncio
import requests # For making HTTP requests to weather API
from geopy.geocoders import Nominatim # For converting location name to coordinates
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
import yfinance as yf # For fetching stock prices
from typing import Dict, Callable, Any, Optional
import logging
from datetime import datetime
import pytz
from timezonefinder import TimezoneFinder

logger = logging.getLogger(__name__)

# Tools are regular async functions.
async def get_weather(location: str):
    """
    Get the current weather for a given location using Open-Meteo API.
    Parameters:
      location (str): The city and state, or just city name e.g., "San Francisco, CA" or "London". This is a required parameter.
    """
    print(f"Executing tool: get_weather(location='{location}')")
    logger.info(f"Attempting to get weather for location: {location}")
    
    geolocator = Nominatim(user_agent="get_weather_tool/1.0")
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

    # Open-Meteo API endpoint
    # We will fetch current temperature and weather code
    # API docs: https://open-meteo.com/en/docs
    weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,weather_code,wind_speed_10m&temperature_unit=celsius&wind_speed_unit=kmh"

    try:
        response = await asyncio.to_thread(requests.get, weather_url, timeout=10)
        response.raise_for_status()  # Raise an exception for HTTP errors (4xx or 5xx)
        data = response.json()
        logger.debug(f"Weather API response for {location}: {data}")

        if "current" in data and "temperature_2m" in data["current"] and "weather_code" in data["current"]:
            temp = data["current"]["temperature_2m"]
            weather_code = data["current"]["weather_code"]
            wind_speed = data["current"].get("wind_speed_10m", "N/A") # wind_speed_10m might not always be there

            # Basic interpretation of WMO weather codes (from Open-Meteo docs)
            # This can be expanded for more descriptive weather
            weather_description = "Clear sky"
            if weather_code == 0: weather_description = "Clear sky"
            elif weather_code == 1: weather_description = "Mainly clear"
            elif weather_code == 2: weather_description = "Partly cloudy"
            elif weather_code == 3: weather_description = "Overcast"
            elif weather_code in (45, 48): weather_description = "Fog"
            elif weather_code in (51, 53, 55): weather_description = "Drizzle"
            elif weather_code in (56, 57): weather_description = "Freezing Drizzle"
            elif weather_code in (61, 63, 65): weather_description = "Rain"
            elif weather_code in (66, 67): weather_description = "Freezing Rain"
            elif weather_code in (71, 73, 75): weather_description = "Snow fall"
            elif weather_code == 77: weather_description = "Snow grains"
            elif weather_code in (80, 81, 82): weather_description = "Rain showers"
            elif weather_code in (85, 86): weather_description = "Snow showers"
            elif weather_code == 95: weather_description = "Thunderstorm"
            elif weather_code in (96, 99): weather_description = "Thunderstorm with hail"
            else: weather_description = f"Weather code {weather_code}"
            
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


async def get_stock_price(stock_symbol: str) -> str:
    """
    Get the current stock price for a given stock or cryptocurrency symbol using Yahoo Finance (yfinance).
    Parameters:
      stock_symbol (str): The stock or cryptocurrency ticker symbol, e.g., "GOOG", "MSFT", or "BTC-USD". This is a required parameter.
    """
    print(f"Executing tool: get_stock_price(stock_symbol='{stock_symbol}')")
    logger.info(f"Attempting to get stock price for symbol: {stock_symbol}")
    
    try:
        ticker = yf.Ticker(stock_symbol)
        # Use history() to get recent data, then pick the last close or current price if available
        # Using 'period="1d"' and 'interval="1m"' can sometimes give more up-to-date info if market is open
        # For simplicity, we'll try to get the most recent 'regularMarketPrice' or 'currentPrice'
        # If market is closed, 'fast_info' might be more reliable for the last closing price.
        
        # Prefer more direct info if available
        info = await asyncio.to_thread(ticker.info.get, 'currentPrice') or \
               await asyncio.to_thread(ticker.info.get, 'regularMarketPrice')
        
        if info is None: # Fallback to history if direct price not found
            hist = await asyncio.to_thread(ticker.history, period="2d") # Get 2 days to ensure we have at least one record
            if not hist.empty:
                info = hist['Close'].iloc[-1]
            else: # If history is also empty, try fast_info
                info = await asyncio.to_thread(getattr, ticker, 'fast_info', {}).get('last_price')


        if info is not None:
            currency = await asyncio.to_thread(ticker.info.get, 'currency', '$') # Default to $ if not found
            logger.info(f"Successfully fetched stock price for {stock_symbol}: {currency}{info:.2f}")
            return f"The current price of {stock_symbol.upper()} is {currency}{info:.2f}."
        else:
            logger.warning(f"Could not retrieve stock price for {stock_symbol}. The symbol might be invalid or data unavailable.")
            return f"Could not retrieve stock price for {stock_symbol}. It might be an invalid symbol or data is temporarily unavailable."
            
    except requests.exceptions.HTTPError as http_err: # yfinance can raise this for invalid symbols
        logger.error(f"HTTP error (likely invalid symbol) for {stock_symbol}: {http_err}", exc_info=True)
        if http_err.response.status_code == 404:
            return f"Stock symbol '{stock_symbol}' not found or invalid."
        return f"Could not fetch stock price for {stock_symbol} (HTTP Error: {http_err.response.status_code})."
    except IndexError: # Can happen if yfinance returns empty data for a symbol
        logger.warning(f"No data returned for stock symbol {stock_symbol}. It might be delisted or invalid.")
        return f"No data found for stock symbol '{stock_symbol}'. It may be delisted or invalid."
    except Exception as e:
        logger.error(f"An unexpected error occurred while fetching stock price for {stock_symbol}: {e}", exc_info=True)
        return f"An error occurred while fetching stock price for {stock_symbol}."

# List of available tools (functions) - can be used to create specific toolsets
master_tool_list: Dict[str, Callable[..., Any]] = {
    "get_weather": get_weather,
    "get_stock_price": get_stock_price,
}