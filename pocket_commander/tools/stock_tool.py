import asyncio
import requests # For making HTTP requests (indirectly via yfinance)
import yfinance as yf # For fetching stock prices
import logging

# Import the @tool decorator
from pocket_commander.tools.decorators import tool

logger = logging.getLogger(__name__)

@tool(name="get_stock_price") # Explicit name for clarity
async def get_stock_price(stock_symbol: str) -> str:
    """Gets the current stock price for a given stock or cryptocurrency symbol.

    Uses Yahoo Finance (yfinance) to fetch the data.

    Args:
        stock_symbol (str): The stock or cryptocurrency ticker symbol (e.g., "GOOG", "MSFT", "BTC-USD").
                            This is a required parameter.
    
    Returns:
        str: A string with the current stock price or an error message.
    """
    logger.info(f"Attempting to get stock price for symbol: {stock_symbol}")
    
    try:
        ticker = yf.Ticker(stock_symbol)
        
        # Attempt to get current price or regular market price first
        info = await asyncio.to_thread(ticker.info.get, 'currentPrice') or \
               await asyncio.to_thread(ticker.info.get, 'regularMarketPrice')
        
        if info is None: # Fallback to history if direct price not found
            hist = await asyncio.to_thread(ticker.history, period="2d") # Get 2 days to ensure we have at least one record
            if not hist.empty:
                info = hist['Close'].iloc[-1]
            else: # If history is also empty, try fast_info (less reliable but a last resort)
                fast_info_data = await asyncio.to_thread(getattr, ticker, 'fast_info', {})
                info = fast_info_data.get('last_price')

        if info is not None:
            currency = await asyncio.to_thread(ticker.info.get, 'currency', '$') # Default to $
            logger.info(f"Successfully fetched stock price for {stock_symbol}: {currency}{float(info):.2f}")
            return f"The current price of {stock_symbol.upper()} is {currency}{float(info):.2f}."
        else:
            logger.warning(f"Could not retrieve stock price for {stock_symbol}. The symbol might be invalid or data unavailable.")
            return f"Could not retrieve stock price for {stock_symbol}. It might be an invalid symbol or data is temporarily unavailable."
            
    except requests.exceptions.HTTPError as http_err: # yfinance can raise this for invalid symbols
        logger.error(f"HTTP error (likely invalid symbol) for {stock_symbol}: {http_err}", exc_info=True)
        if hasattr(http_err, 'response') and http_err.response is not None and http_err.response.status_code == 404:
            return f"Stock symbol '{stock_symbol}' not found or invalid."
        return f"Could not fetch stock price for {stock_symbol} (HTTP Error: {getattr(http_err.response, 'status_code', 'Unknown')})."
    except IndexError: 
        logger.warning(f"No data returned for stock symbol {stock_symbol}. It might be delisted or invalid.")
        return f"No data found for stock symbol '{stock_symbol}'. It may be delisted or invalid."
    except Exception as e:
        logger.error(f"An unexpected error occurred while fetching stock price for {stock_symbol}: {e}", exc_info=True)
        return f"An error occurred while fetching stock price for {stock_symbol}."