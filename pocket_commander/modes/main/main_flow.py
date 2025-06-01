#%%
# pocket_commander/modes/main/main_flow.py
import inspect
import asyncio
from typing import Dict, Optional

from pocket_commander.commands.core import CommandMetadata, CommandContext
from pocket_commander.commands.decorators import command
from pocket_commander.commands.terminal_io import TerminalCommandInput, TerminalOutputHandler
# Ensure TerminalApp is imported for type hinting if not already via a full path
from pocket_commander.terminal_interface import TerminalApp


class MainModeFlow:
    def __init__(self, mode_config: Dict, terminal_app_instance: 'TerminalApp'):
        self.mode_config = mode_config
        self.terminal_app = terminal_app_instance
        self.logger = self.terminal_app.console # Using console for logging for now
        self._commands: Dict[str, CommandMetadata] = self._discover_commands()

        self.terminal_app.display_output(
            f"Main Mode Flow initialized. Description: {self.mode_config.get('description', 'N/A')}",
            style="dim"
        )
        self.terminal_app.display_output(
            f"Discovered commands: {list(self._commands.keys())}",
            style="dim"
        )

    def _discover_commands(self) -> Dict[str, CommandMetadata]:
        """
        Discovers methods decorated with @command in this class and registers them.
        """
        cmds: Dict[str, CommandMetadata] = {}
        for _, member in inspect.getmembers(self):
            if callable(member) and hasattr(member, '_command_metadata'):
                meta: CommandMetadata = getattr(member, '_command_metadata')
                if meta.name in cmds:
                    self.logger.print(f"[yellow]Warning: Duplicate command name '{meta.name}' found. Overwriting.[/yellow]")
                cmds[meta.name] = meta
                for alias in meta.aliases:
                    if alias in cmds:
                        self.logger.print(f"[yellow]Warning: Duplicate command alias '{alias}' found. Overwriting.[/yellow]")
                    cmds[alias] = meta
        return cmds

    async def handle_input(self, user_input: str):
        """
        Handles input for the main mode.
        Parses the input for a command and dispatches it if found.
        Otherwise, echoes the input.
        """
        stripped_input = user_input.strip()
        if not stripped_input:
            return

        parts = stripped_input.split(maxsplit=1)
        command_name = parts[0]
        remaining_input_str = parts[1] if len(parts) > 1 else ""

        if command_name in self._commands:
            cmd_meta = self._commands[command_name]
            
            # Create I/O handlers and context
            # TerminalCommandInput takes the command word and the rest of the string
            cmd_input = TerminalCommandInput(command_name, remaining_input_str, self.terminal_app)
            cmd_output = TerminalOutputHandler(self.terminal_app)
            
            ctx = CommandContext(
                input=cmd_input,
                output=cmd_output,
                mode_name="main", # Or self.mode_config.get('name', 'main')
                terminal_app=self.terminal_app,
                mode_flow=self,
                loop=asyncio.get_event_loop()
            )

            try:
                # Call the command function (it's a method of self)
                # The decorator ensures cmd_meta.func is the original async method
                await cmd_meta.func(self, ctx)
            except Exception as e:
                # This is a fallback if the command itself doesn't handle its errors
                self.logger.print_exception(show_locals=True) # For debugging
                await ctx.output.send_error(
                    f"An unexpected error occurred while executing command '{command_name}'.",
                    details=str(e)
                )
        else:
            # Default behavior: echo if no command is found
            echo_response = f"Main Mode (Unknown Command - Echo): {user_input}"
            self.terminal_app.display_output(echo_response, style="italic green")

    # --- Example Command ---
    @command(name="greet", description="Greets the user or a specified name.", aliases=["hello"])
    async def greet_command(self, ctx: CommandContext):
        """
        Example command: Greets the user.
        Takes an optional name as an argument. e.g., "greet World"
        """
        # TerminalCommandInput's raw_input is the string *after* the command word.
        name_arg = ctx.input.raw_input.strip()
        
        if not name_arg: # If no name is provided after "greet"
            # Try to get it from mode_config as a fallback, or use a default
            name_arg = self.mode_config.get("default_greet_name", "User from Main Mode")
            
        await ctx.output.send_message(f"Hello, {name_arg}!", style="bold magenta")
        await ctx.output.send_data({"recipient": name_arg, "message": "Hello"}, format_hint="json")

    @command(name="modeinfo", description="Shows information about the current mode.")
    async def mode_info_command(self, ctx: CommandContext):
        """Displays configuration of the current mode."""
        await ctx.output.send_message("Current Mode Configuration:", style="bold blue")
        await ctx.output.send_data(self.mode_config, format_hint="json")


def create_main_flow(mode_config: Dict, terminal_app_instance: 'TerminalApp'):
    """
    Factory function to create an instance of the MainModeFlow.
    """
    return MainModeFlow(mode_config, terminal_app_instance)