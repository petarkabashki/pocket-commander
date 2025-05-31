# Add the search_web function
import logging

logger = logging.getLogger(__name__)

def search_web(query: str) -> str:
    """
    Search the web for information.
    :param query: The search query.
    """
    logger.info(f"Executing search_web with query: '{query}'")
    # Simulate web search
    if "Nobel Prize in Physics 2024" in query:
        return "The Nobel Prize in Physics 2024 has not been announced yet. It is typically announced in early October."
    elif "current time in London" in query:
        return "The current time in London is 1:45 AM BST, Friday, May 31, 2025." # Example, actual time would vary
    else:
        return f"Search results for '{query}': No specific information found for this mock query."

if __name__ == '__main__':
    # Example usage for testing
    logging.basicConfig(level=logging.INFO)
    print(search_web(query="Nobel Prize in Physics 2024"))
    print(search_web(query="What is the capital of France?"))
    print(search_web(query="current time in London"))