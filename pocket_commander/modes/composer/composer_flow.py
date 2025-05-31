#%%
# pocket_commander/modes/composer/composer_flow.py

class ComposerModeFlow:
    def __init__(self, mode_config, terminal_app_instance):
        self.mode_config = mode_config
        self.terminal_app = terminal_app_instance
        self.logger = self.terminal_app.console # Or get a proper logger

        self.terminal_app.display_output(
            f"Composer Mode Flow initialized. Config: {self.mode_config.get('description')}",
            style="dim"
        )

    async def handle_input(self, user_input: str):
        """
        Handles input for the composer mode.
        For this simple example, it just echoes the input.
        """
        echo_response = f"Composer Mode Echo: {user_input}"
        self.terminal_app.display_output(echo_response, style="italic blue")
        
        # Example of using a specific LLM profile if needed later
        # llm_profile_name = self.mode_config.get("llm_profile", "default")
        # self.terminal_app.display_output(f"LLM Profile for Composer Mode: {llm_profile_name}", style="dim")

def create_composer_flow(mode_config, terminal_app_instance):
    """
    Factory function to create an instance of the ComposerModeFlow.
    """
    return ComposerModeFlow(mode_config, terminal_app_instance)