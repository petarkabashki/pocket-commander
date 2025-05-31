import logging
from ..pocketflow import AsyncNode # Corrected import

logger = logging.getLogger(__name__)

class InitialQueryNode(AsyncNode):
    def __init__(self, max_retries=2, wait=1): # Default retries/wait for this node type
        super().__init__(max_retries=max_retries, wait=wait)
        logger.debug(f"InitialQueryNode initialized with max_retries={self.max_retries}, wait={self.wait}s")

    async def prep_async(self, shared):
        """
        Retrieves the initial query from the shared store.
        """
        query = shared.get('query')
        if not query:
            logger.error("Prep: 'query' not found in shared store or is empty.")
            # Option 1: Raise error
            raise ValueError("'query' is required in shared store and cannot be empty for InitialQueryNode.")
            # Option 2: Provide a default query (less ideal for a generic node)
            # query = "What is the meaning of life?"
            # logger.warning(f"Prep: 'query' not found, using default: '{query}'")
        
        logger.debug(f"Prep: Initial query retrieved: '{query}'")
        return query

    async def exec_async(self, prep_res):
        """
        Formats the query into the initial list of messages.
        """
        query = prep_res
        initial_messages = [{'role': 'user', 'content': query}]
        logger.debug(f"Exec: Prepared initial messages: {initial_messages}")
        return initial_messages

    async def post_async(self, shared, prep_res, exec_res):
        """
        Updates the shared store with the query and initial messages.
        """
        query = prep_res # The original query from prep
        initial_messages = exec_res # The messages list from exec

        shared['query'] = query # Ensure shared query is consistent
        shared['messages'] = initial_messages # Set the messages history

        logger.info(f"Post: Shared store updated. Query: '{shared['query']}', Initial Messages: {shared['messages']}")
        return "default" # Standard action to proceed