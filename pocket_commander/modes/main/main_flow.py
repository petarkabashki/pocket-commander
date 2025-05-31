#%%
# pocket_commander/modes/main/main_flow.py

class MainModeFlow:
    def __init__(self, mode_config, terminal_app_instance):
        self.mode_config = mode_config
        self.terminal_app = terminal_app_instance
        self.logger = self.terminal_app.console # Or get a proper logger

        self.terminal_app.display_output(
            f"Main Mode Flow initialized. Config: {self.mode_config.get('description')}",
            style="dim"
        )

    async def handle_input(self, user_input: str):
        """
        Handles input for the main mode.
        For this simple example, it just echoes the input.
        """
        echo_response = f"Main Mode Echo: {user_input}"
        self.terminal_app.display_output(echo_response, style="italic green")
        
        # Example of using a specific LLM profile if needed later
        # llm_profile_name = self.mode_config.get("llm_profile", "default")
        # self.terminal_app.display_output(f"LLM Profile for Main Mode: {llm_profile_name}", style="dim")


def create_main_flow(mode_config, terminal_app_instance):
    """
    Factory function to create an instance of the MainModeFlow.
    """
    return MainModeFlow(mode_config, terminal_app_instance)