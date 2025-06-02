import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine, Dict, List, Type, TypeVar
import time # Added import

from pydantic import BaseModel, Field
import uuid # For unique event IDs

logger = logging.getLogger(__name__)

# Generic type for event instances
E = TypeVar("E", bound="BaseEvent")

# Type for an event handler coroutine
EventHandler = Callable[[E], Coroutine[Any, Any, None]]


class BaseEvent(BaseModel):
    """
    Base class for all events in the system.
    Includes a unique event ID and a timestamp.
    """
    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    timestamp: float = Field(default_factory=time.time) # Changed from asyncio.get_running_loop().time

    class Config:
        arbitrary_types_allowed = True # For potential complex types in subclasses


class AsyncEventBus:
    """
    An asynchronous event bus for decoupled communication between components.
    """

    def __init__(self):
        self._subscribers: Dict[Type[BaseEvent], List[EventHandler]] = defaultdict(list)
        self._event_queue = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None
        self._running = False

    async def subscribe(self, event_type: Type[E], handler: EventHandler[E]):
        """
        Subscribes a handler coroutine to a specific event type.
        """
        if not asyncio.iscoroutinefunction(handler):
            raise TypeError(f"Handler for {event_type.__name__} must be a coroutine function.")
        
        self._subscribers[event_type].append(handler)
        logger.debug(f"Handler {handler.__name__} subscribed to event type {event_type.__name__}")

    async def publish(self, event: BaseEvent):
        """
        Publishes an event to all subscribed handlers for its type.
        Events are put onto an internal queue and processed by a worker task.
        """
        if not self._running:
            logger.warning(f"Event bus is not running. Event {type(event).__name__} ({event.event_id}) will not be processed immediately.")
            # Optionally, queue even if not running, or raise error
        
        await self._event_queue.put(event)
        logger.debug(f"Event {type(event).__name__} ({event.event_id}) published to queue.")

    async def _process_event(self, event: BaseEvent):
        """
        Processes a single event by calling all relevant subscribers.
        """
        event_type = type(event)
        handlers_to_call: List[EventHandler] = []

        # Get handlers for the exact event type
        if event_type in self._subscribers:
            handlers_to_call.extend(self._subscribers[event_type])
        
        # Optional: Add handlers for parent event types (if BaseEvent is a common ancestor)
        # For now, only exact type match for simplicity.
        # If you want to support inheritance (e.g. subscribing to BaseEvent gets all events):
        # for sub_type, handlers in self._subscribers.items():
        #     if isinstance(event, sub_type) and sub_type != event_type : # Avoid double-adding exact match
        #         handlers_to_call.extend(handlers)


        if not handlers_to_call:
            logger.debug(f"No subscribers for event type {event_type.__name__} ({event.event_id})")
            return

        logger.debug(f"Processing event {event_type.__name__} ({event.event_id}) for {len(handlers_to_call)} handler(s).")
        
        tasks = [handler(event) for handler in handlers_to_call]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result, handler in zip(results, handlers_to_call):
            if isinstance(result, Exception):
                logger.error(
                    f"Error in event handler {handler.__name__} for event {event_type.__name__} ({event.event_id}): {result}",
                    exc_info=result
                )

    async def _worker(self):
        """
        The main worker coroutine that pulls events from the queue and processes them.
        """
        while self._running or not self._event_queue.empty():
            try:
                event = await asyncio.wait_for(self._event_queue.get(), timeout=1.0)
                if event is None: # Sentinel for shutdown
                    self._event_queue.task_done()
                    break 
                await self._process_event(event)
                self._event_queue.task_done()
            except asyncio.TimeoutError:
                # Just to allow checking self._running periodically
                continue
            except Exception as e:
                logger.error(f"Error in event bus worker: {e}", exc_info=True)
                # Potentially requeue event or handle error more gracefully
        logger.info("Event bus worker stopped.")


    async def start(self):
        """
        Starts the event bus worker task.
        """
        if self._running:
            logger.info("Event bus is already running.")
            return
        
        self._running = True
        self._worker_task = asyncio.create_task(self._worker())
        logger.info("Event bus worker started.")

    async def stop(self, graceful_shutdown_timeout: float = 5.0):
        """
        Stops the event bus worker task.
        Allows pending events to be processed up to a timeout.
        """
        if not self._running and (self._worker_task is None or self._worker_task.done()):
            logger.info("Event bus is not running or already stopped.")
            return

        logger.info("Stopping event bus worker...")
        self._running = False # Signal worker to stop after processing current queue
        
        # Add a sentinel value to unblock the queue if it's empty and worker is waiting
        await self._event_queue.put(None)

        if self._worker_task:
            try:
                await asyncio.wait_for(self._worker_task, timeout=graceful_shutdown_timeout)
                logger.info("Event bus worker task finished.")
            except asyncio.TimeoutError:
                logger.warning(f"Event bus worker did not finish in {graceful_shutdown_timeout}s. Cancelling task.")
                self._worker_task.cancel()
                try:
                    await self._worker_task
                except asyncio.CancelledError:
                    logger.info("Event bus worker task cancelled.")
            except Exception as e:
                logger.error(f"Exception during event bus stop: {e}", exc_info=True)
        
        # Process any remaining events if timeout occurred and queue is not empty
        # This part is tricky; ideally, the worker handles its queue.
        # For simplicity, we assume the worker tries its best within the timeout.
        if not self._event_queue.empty():
            logger.warning(f"Event bus stopped, but {self._event_queue.qsize()} events remain in queue.")

        self._worker_task = None
        logger.info("Event bus definitively stopped.")

# Example Usage (can be removed or kept for testing)
async def my_event_handler(event: BaseEvent):
    logger.info(f"Handler 1: Received event {type(event).__name__} with ID {event.event_id} at {event.timestamp}")
    await asyncio.sleep(0.1) # Simulate work

class SpecificEvent(BaseEvent):
    message: str

async def specific_event_handler(event: SpecificEvent):
    logger.info(f"Handler 2: Received SpecificEvent with message '{event.message}' and ID {event.event_id}")
    await asyncio.sleep(0.2)

async def main_test():
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    bus = AsyncEventBus()
    await bus.start()

    await bus.subscribe(BaseEvent, my_event_handler)
    await bus.subscribe(SpecificEvent, specific_event_handler)
    
    await bus.publish(BaseEvent())
    await bus.publish(SpecificEvent(message="Hello from SpecificEvent!"))
    await bus.publish(BaseEvent()) # Will also be caught by my_event_handler

    # Give some time for events to be processed from the queue
    await asyncio.sleep(1) 
    
    await bus.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main_test())
    except KeyboardInterrupt:
        logger.info("Test interrupted by user.")