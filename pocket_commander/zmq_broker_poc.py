#%%
import zmq
import zmq.asyncio
import logging
import signal
import asyncio

# Logging will be configured by the main application if this script is run directly,
# or by the parent process if imported/spawned.

# Global variable to control the main loop
running = True

def handle_signal(signum, frame):
    """Handles termination signals."""
    global running
    logging.info(f"Signal {signum} received, shutting down broker...")
    running = False

async def run_broker(frontend_addr: str = "tcp://*:5559", backend_addr: str = "tcp://*:5560", control_addr: str = "inproc://broker_control"):
    """
    Runs a simple ZeroMQ XPUB/XSUB forwarder broker.
    Publishers connect to the frontend (XSUB).
    Subscribers connect to the backend (XPUB).
    """
    global running
    context = zmq.asyncio.Context()

    frontend_socket = None
    backend_socket = None
    control_socket = None # For steerable proxy

    try:
        # Frontend socket (for publishers)
        frontend_socket = context.socket(zmq.XSUB)
        frontend_socket.bind(frontend_addr)
        logging.info(f"Broker XSUB frontend bound to {frontend_addr}")

        # Backend socket (for subscribers)
        backend_socket = context.socket(zmq.XPUB)
        # XPUB can receive subscription messages from subscribers
        # Set XPUB_VERBOSE to 1 to see all subscription messages
        # backend_socket.setsockopt(zmq.XPUB_VERBOSE, 1) # Optional: for debugging subscriptions
        backend_socket.bind(backend_addr)
        logging.info(f"Broker XPUB backend bound to {backend_addr}")

        # Control socket for the proxy
        control_socket = context.socket(zmq.PUB)
        control_socket.bind(control_addr)
        logging.info(f"Broker control socket bound to {control_addr}")

        logging.info("Broker started. Waiting for publishers and subscribers...")
        logging.info("Press Ctrl+C to stop.")

        # Start the steerable proxy. This handles message forwarding.
        # zmq.proxy_steerable is blocking, so we run it in a separate thread
        # or adapt it for asyncio if a fully async version is available/needed.
        # For PoC, a simple loop might be more illustrative if proxy_steerable is tricky with asyncio.
        # Let's try a manual polling loop for more explicit control and asyncio integration.

        # Use zmq.proxy for robust forwarding.
        # Note: zmq.proxy is blocking, so it needs to be run in a way that doesn't block asyncio.
        # For an asyncio context, zmq.device.Proxy might be better, or running proxy in a thread.
        # However, the original code was using asyncio sockets with a manual poll loop.
        # To keep it async and simple for now, let's adapt the manual loop slightly,
        # or consider if zmq.asyncio.proxy is available or if we should run blocking proxy in executor.

        # The simplest async proxy is zmq.asyncio.proxy_async
        # It requires a control socket for termination.
        
        # Create a termination signal for the proxy
        proxy_term_future = asyncio.Future()

        async def proxy_task():
            try:
                # zmq.asyncio.proxy_async is the correct way to run a proxy in an asyncio event loop.
                # It takes frontend, backend, and optionally a capture socket.
                # For termination, it relies on the context being terminated or sockets being closed.
                # A common pattern is to use a control socket with proxy_steerable_async
                # or manage termination by closing sockets/context.
                
                # Let's use proxy_steerable_async as it's designed for graceful shutdown.
                # control_socket was already bound.
                logging.info("Starting steerable proxy...")
                await zmq.asyncio.proxy_steerable(frontend_socket, backend_socket, control=control_socket)
            except zmq.error.ContextTerminated:
                logging.info("Proxy task: Context terminated.")
            except asyncio.CancelledError:
                logging.info("Proxy task cancelled.")
            except Exception as e:
                logging.error(f"Proxy task error: {e}", exc_info=True)
            finally:
                logging.info("Proxy task finished.")
                if not proxy_term_future.done():
                    proxy_term_future.set_result(True)

        proxy_runner_task = asyncio.create_task(proxy_task())
        
        # Keep broker running until signal is received
        while running:
            await asyncio.sleep(0.5) # Check running flag periodically
            if proxy_runner_task.done(): # If proxy stops for any reason
                logging.warning("Proxy runner task finished unexpectedly. Broker will stop.")
                break 
        
        logging.info("Broker `running` flag is false. Terminating proxy...")
        # Terminate the proxy by closing the control socket or context
        if control_socket and not control_socket.closed:
            # Sending a "TERMINATE" message on control socket is one way for steerable proxy
            # For proxy_steerable, closing the context or sockets is more direct.
            # control_socket.send_string("TERMINATE") # This might not work if proxy isn't listening to it for termination.
            # Closing the context is a more forceful way to stop the proxy.
            # Or, cancel the proxy_runner_task.
            pass # Sockets will be closed in finally block. Context termination will stop it.

        if proxy_runner_task and not proxy_runner_task.done():
            proxy_runner_task.cancel()
            try:
                await proxy_runner_task
            except asyncio.CancelledError:
                logging.info("Proxy runner task successfully cancelled during shutdown.")
        
        # Ensure future is resolved if proxy task didn't set it (e.g. if loop exited before proxy task completed)
        if not proxy_term_future.done():
            proxy_term_future.set_result(True)

    except KeyboardInterrupt: # Should be caught by signal handler
        logging.info("KeyboardInterrupt received, broker shutting down...")
    except Exception as e:
        logging.error(f"An unexpected error occurred in broker: {e}", exc_info=True)
    finally:
        logging.info("Broker cleaning up...")
        if poller:
            if frontend_socket and not frontend_socket.closed: poller.unregister(frontend_socket)
            if backend_socket and not backend_socket.closed: poller.unregister(backend_socket)
        if frontend_socket and not frontend_socket.closed:
            frontend_socket.close()
            logging.info("Frontend socket closed.")
        if backend_socket and not backend_socket.closed:
            backend_socket.close()
            logging.info("Backend socket closed.")
        if control_socket and not control_socket.closed: # Though not used in poller loop
            control_socket.close()
            logging.info("Control socket closed.")
        if not context.closed:
            context.term()
            logging.info("ZMQ context terminated.")
        logging.info("Broker shutdown complete.")

async def main():
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Define broker addresses (could be loaded from config)
    frontend_address = "tcp://*:5559"
    backend_address = "tcp://*:5560"
    # control_address = "inproc://broker_control_poc" # For steerable proxy, not used in manual loop

    await run_broker(frontend_addr=frontend_address, backend_addr=backend_address)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Broker process terminated by KeyboardInterrupt in __main__.")
    except Exception as e:
        logging.critical(f"Broker process failed critically in __main__: {e}", exc_info=True)

#%%