#%%
import asyncio
import logging
from typing import Callable, Awaitable, Any, Optional, List

logger = logging.getLogger(__name__)
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import WordCompleter, Completer, Completion
from prompt_toolkit.document import Document
from rich.console import Console
from rich.text import Text

from pocket_commander.commands.io import AbstractCommandInput # AbstractOutputHandler is in AppServices
from pocket_commander.commands.terminal_io import TerminalCommandInput, TerminalOutputHandler
from pocket_commander.types import AppServices # For type hinting

class AppStateAwareCompleter(Completer):
    """
    A prompt-toolkit completer that is aware of the application's state
    to provide dynamic command completions.
    """
    def __init__(self, app_services_provider: Callable[[], AppServices]):
        self.app_services_provider = app_services_provider

    def get_completions(self, document: Document, complete_event) -> List[Completion]:
        completions: List[str] = []
        app_services = self.app_services_provider()
        
        # This is a simplified way to access state.
        # In a real scenario, app_core would expose functions to get this data.
        # For now, we'll assume app_services might hold a reference or a getter
        # to the current application_state dictionary or relevant parts.
        # This part needs to be carefully designed with how app_core exposes its state.
        
        # Placeholder: Assume app_services has a way to get global and mode commands
        # This is a temporary simplification.
        raw_config = app_services.get('raw_app_config', {})
        # This is a hacky way to get at the state for now.
        # A proper observer pattern or callback to app_core would be better.
        # For the purpose of this refactor, we'll assume app_core updates
        # something in app_services or provides a getter.
        # Let's assume app_core.py will update a 'current_command_completions' in app_services for TIF.
        
        # For now, let's use a simpler approach: get config and make some guesses
        # This part will need refinement once app_core.py is fully integrated with main.py
        
        # Global commands (conventionally prefixed with /)
        # We'd ideally get these from application_state['global_commands'] via app_services
        completions.extend(["/exit", "/quit", "/q", "/help", "/modes", "/mode", "/tools", "/tool"])

        # Mode names for /mode command
        available_modes = raw_config.get('modes', {})
        completions.extend(list(available_modes.keys()))

        # Active mode commands (we don't have direct access to active_mode_commands here yet)
        # This is where the dependency on app_core's state becomes tricky without a proper interface.
        # For now, this completer will be basic.
        # A more robust solution would involve app_core providing a method to get current completions.

        word_before_cursor = document.get_word_before_cursor(WORD=True)
        for cmd_name in completions:
            if cmd_name.startswith(word_before_cursor):
                yield Completion(cmd_name, start_position=-len(word_before_cursor))


class TerminalInteractionFlow:
    """
    Manages terminal-specific user interaction using prompt-toolkit and Rich.
    Captures input and passes it to the provided input processing callback.
    Provides concrete I/O handlers (output, prompt) for the application.
    """

    def __init__(
        self, 
        app_services: AppServices, # Provides access to shared state/config for prompt, completions
        process_input_callback: Callable[[str, AbstractCommandInput], Awaitable[Any]]
    ):
        self.app_services = app_services
        self.process_input_callback = process_input_callback
        self.console = Console()
        self.session = PromptSession(history=FileHistory('.terminal_history'))
        
        # The completer needs access to AppServices to get current command lists
        # We pass a callable that returns the current AppServices instance.
        self.command_completer = AppStateAwareCompleter(lambda: self.app_services)
        self._running = False
        self._output_handler = TerminalOutputHandler(self.console) # Create and store one instance

    def get_output_handler(self) -> TerminalOutputHandler:
        """Provides the TerminalOutputHandler instance for use by the application."""
        return self._output_handler

    async def request_dedicated_input(self, prompt_message: str, style: Optional[str] = None) -> str:
        """
        Concrete implementation of PromptFunc.
        Requests dedicated, interactive user input.
        """
        # prompt-toolkit's prompt_async doesn't directly take a Rich style string for the prompt itself.
        # We can print the styled message first, then prompt.
        if style:
            self.console.print(Text(prompt_message, style=style), end=" ") # end=" " to keep on same line
        else:
            self.console.print(prompt_message, end=" ")
        
        # The actual input prompt will use default styling or session's style
        user_response = await self.session.prompt_async("") # Empty prompt string as message is pre-printed
        return user_response.strip()

    async def start(self):
        """Starts the terminal interaction loop."""
        self._running = True
        logger.info("TerminalInteractionFlow started.")
        self.console.print("[bold cyan]Welcome to Pocket Commander![/bold cyan]")
        # Initial message (like no default mode) will be sent by app_core via output_handler
        await self._main_loop()

    async def stop(self):
        """Stops the terminal interaction loop."""
        if self._running:
            self._running = False
            logger.info("TerminalInteractionFlow stopping.")
            # Attempt to gracefully close the prompt session if it's waiting
            # This might involve cancelling the prompt_async task if possible,
            # or relying on the loop check. For now, setting _running to False.
            # prompt_toolkit's Application object has a `exit()` method if we were using full App.

    async def _main_loop(self):
        """The main input processing loop."""
        while self._running:
            try:
                # Dynamically determine prompt based on app_services (indirectly from app_state)
                # This is a simplification. A cleaner way would be for app_core to provide this.
                current_mode_name = "N/A" # Default
                # logger.debug(f"TIF: Attempting to get _application_state_DO_NOT_USE_DIRECTLY from app_services. Value: {self.app_services.get('_application_state_DO_NOT_USE_DIRECTLY')}")
                if self.app_services.get('_application_state_DO_NOT_USE_DIRECTLY'): # HACK
                    current_mode_name = self.app_services['_application_state_DO_NOT_USE_DIRECTLY'].get('active_mode_name', "N/A")
                
                prompt_text = f"({current_mode_name})> "
                
                user_input_str = await self.session.prompt_async(
                    prompt_text,
                    auto_suggest=AutoSuggestFromHistory(),
                    completer=self.command_completer, # Use the AppStateAwareCompleter
                    # refresh_interval=0.5 # Can be useful if completer state changes often
                )

                if not self._running: break

                command_input = TerminalCommandInput(user_input_str)
                await self.process_input_callback(user_input_str, command_input)

            except KeyboardInterrupt:
                self.console.print("\n[italic yellow]Keyboard interrupt. Type /exit to quit.[/italic yellow]")
                # Let app_core handle /exit if it's typed next
            except EOFError:
                self.console.print("\n[bold red]EOF received. Exiting...[/bold red]")
                # Simulate /exit command to trigger graceful shutdown in app_core
                try:
                    await self.process_input_callback("/exit", TerminalCommandInput("/exit"))
                except SystemExit: # Expected from /exit
                    pass 
                break # Exit TIF loop
            except SystemExit: # Raised by /exit command in app_core
                logger.info("SystemExit caught in TIF, propagating to stop.")
                await self.stop() # Ensure TIF stops its loop
                raise # Re-raise to stop the main application
            except Exception as e:
                self.console.print(f"[bold red]An unexpected error occurred in terminal interaction: {e}[/bold red]")
                logger.exception("Terminal interaction loop error")

        logger.info("Terminal interaction loop ended.")
        self.console.print("Goodbye!")