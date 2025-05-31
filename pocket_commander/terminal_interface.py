#%%
import asyncio
import importlib
import yaml # Assuming PyYAML is or will be a dependency for config loading

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import WordCompleter # For command completion
from rich.console import Console
from rich.text import Text

# Configuration file path (adjust if necessary)
CONFIG_PATH = "pocket_commander.conf.yaml"

class TerminalApp:
    def __init__(self):
        self.console = Console()
        self.session = PromptSession(history=FileHistory('.terminal_history')) # Persist history
        self.modes_config = {}
        self.current_mode_name = None
        self.current_mode_flow = None
        self.load_config()
        self.set_initial_mode()

        # Basic command completer
        self.command_completer = WordCompleter([
            '/help', '/commands', '/modes', 'mode'
            # Mode names will be added dynamically
        ], ignore_case=True)

    def load_config(self):
        try:
            with open(CONFIG_PATH, 'r') as f:
                config = yaml.safe_load(f)
            self.modes_config = config.get("terminal_modes", {})
            if not self.modes_config:
                self.console.print("[bold red]Error: 'terminal_modes' not found in config or is empty.[/bold red]")
                # Potentially exit or handle gracefully
            # Update completer with mode names
            if hasattr(self, 'command_completer') and self.modes_config:
                 self.command_completer.words.extend(list(self.modes_config.keys()))
        except FileNotFoundError:
            self.console.print(f"[bold red]Error: Configuration file '{CONFIG_PATH}' not found.[/bold red]")
            # Potentially exit or handle gracefully
        except yaml.YAMLError as e:
            self.console.print(f"[bold red]Error parsing configuration file: {e}[/bold red]")
            # Potentially exit or handle gracefully

    def set_initial_mode(self):
        if self.modes_config:
            # Set to 'main' if it exists, otherwise the first mode in the config
            initial_mode_name = "main" if "main" in self.modes_config else next(iter(self.modes_config), None)
            if initial_mode_name:
                self.switch_mode(initial_mode_name, is_initial_setup=True)
            else:
                self.console.print("[bold red]Error: No modes defined in configuration to set an initial mode.[/bold red]")
        else:
            self.console.print("[bold red]Cannot set initial mode: No modes configuration loaded.[/bold red]")


    def switch_mode(self, mode_name: str, is_initial_setup: bool = False):
        if mode_name not in self.modes_config:
            self.console.print(f"[bold red]Error: Mode '{mode_name}' not found in configuration.[/bold red]")
            return

        mode_config = self.modes_config[mode_name]
        flow_module_path = mode_config.get("flow_module")

        if not flow_module_path:
            self.console.print(f"[bold red]Error: 'flow_module' not defined for mode '{mode_name}'.[/bold red]")
            return

        try:
            # Dynamically import the module
            module = importlib.import_module(flow_module_path)
            if hasattr(module, 'get_flow'):
                # Pass the mode_config and a reference to this TerminalApp instance
                self.current_mode_flow = module.get_flow(mode_config, self)
                self.current_mode_name = mode_name
                if not is_initial_setup: # Don't print during initial setup
                    self.console.print(f"Switched to mode: [bold green]{self.current_mode_name}[/bold green]")
                # Update prompt completer if needed or other mode-specific setups
            else:
                self.console.print(f"[bold red]Error: 'get_flow' function not found in module '{flow_module_path}' for mode '{mode_name}'.[/bold red]")
                self.current_mode_flow = None # Ensure flow is reset if loading fails
        except ImportError as e:
            self.console.print(f"[bold red]Error importing flow module '{flow_module_path}' for mode '{mode_name}': {e}[/bold red]")
            self.current_mode_flow = None # Ensure flow is reset if loading fails
        except Exception as e:
            self.console.print(f"[bold red]Error loading flow for mode '{mode_name}': {e}[/bold red]")
            self.current_mode_flow = None


    def display_output(self, content, style: str = None):
        """Displays output to the console, potentially with Rich styling."""
        if style:
            self.console.print(Text(str(content), style=style))
        else:
            self.console.print(content)

    def handle_builtin_command(self, user_input: str):
        parts = user_input.strip().split()
        command = parts[0].lower()
        args = parts[1:]

        if command == "/help":
            self.display_output("Available commands:", style="bold yellow")
            self.display_output("  /help          - Show this help message.")
            self.display_output("  /commands      - List available built-in commands.")
            self.display_output("  /modes         - List available modes.")
            self.display_output("  /mode <name>   - Switch to the specified mode.")
            self.display_output("  /exit          - Exit the terminal.")
            # Potentially list mode-specific commands if current_mode_flow has a method for it
        elif command == "/commands":
            self.display_output("Built-in commands: /help, /commands, /modes, /mode <name>, /exit", style="bold yellow")
        elif command == "/modes":
            self.display_output("Available modes:", style="bold yellow")
            if self.modes_config:
                for name, config in self.modes_config.items():
                    description = config.get('description', 'No description')
                    self.display_output(f"  - {name}: {description}")
            else:
                self.display_output("  No modes configured.", style="italic")
        elif command == "/mode":
            if args:
                self.switch_mode(args[0])
            else:
                self.display_output("Usage: /mode <mode_name>", style="yellow")
        else:
            return False # Not a recognized built-in command
        return True


    async def run(self):
        self.console.print("[bold cyan]Welcome to PocketFlow Terminal![/bold cyan]")
        self.console.print("Type '/help' for a list of commands.")
        if not self.current_mode_name or not self.current_mode_flow:
            self.console.print("[bold red]Critical Error: No initial mode could be set. Please check configuration.[/bold red]")
            self.console.print("You might need to define a 'main' mode or ensure at least one mode is correctly configured.")
            return # Exit if no mode could be loaded

        while True:
            try:
                prompt_text = f"({self.current_mode_name})> "
                user_input = await self.session.prompt_async(
                    prompt_text,
                    auto_suggest=AutoSuggestFromHistory(),
                    completer=self.command_completer # Use the basic completer
                )

                if user_input.strip().lower() == "/exit":
                    self.console.print("Exiting PocketFlow Terminal. Goodbye!")
                    break

                if user_input.startswith("/"):
                    if self.handle_builtin_command(user_input):
                        continue # Command handled, loop again

                # If not a built-in command, pass to the current mode's flow
                if self.current_mode_flow and hasattr(self.current_mode_flow, 'handle_input'):
                    # Assuming the flow has an async method 'handle_input'
                    await self.current_mode_flow.handle_input(user_input)
                elif self.current_mode_flow:
                    self.display_output(f"Mode '{self.current_mode_name}' does not have a 'handle_input' method.", style="yellow")
                else:
                    self.display_output("No active mode or flow to handle input.", style="red")

            except KeyboardInterrupt:
                self.console.print("\nExiting via KeyboardInterrupt. Goodbye!")
                break
            except EOFError: # Ctrl-D
                self.console.print("\nExiting via EOF. Goodbye!")
                break
            except Exception as e:
                self.console.print(f"[bold red]An unexpected error occurred: {e}[/bold red]")
                # Optionally, log the full traceback for debugging
                # self.console.print_exception()

if __name__ == '__main__':
    # This is a placeholder for how you might run the terminal app.
    # You'll likely integrate this into your existing main.py or a new entry script.
    app = TerminalApp()
    asyncio.run(app.run())