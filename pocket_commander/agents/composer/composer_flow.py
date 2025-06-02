#%%
# pocket_commander/agents/composer/composer_flow.py

class ComposerAgentFlow:
    def __init__(self, agent_config, terminal_app_instance):
        self.agent_config = agent_config
        self.terminal_app = terminal_app_instance
        self.logger = self.terminal_app.console # Or get a proper logger

        self.terminal_app.display_output(
            f"Composer Agent Flow initialized. Config: {self.agent_config.get('description')}",
            style="dim"
        )

    async def handle_input(self, user_input: str):
        """
        Handles input for the composer agent.
        For this simple example, it just echoes the input.
        """
        echo_response = f"Composer Agent Echo: {user_input}"
        self.terminal_app.display_output(echo_response, style="italic blue")
        
        # Example of using a specific LLM profile if needed later
        # llm_profile_name = self.agent_config.get("llm_profile", "default")
        # self.terminal_app.display_output(f"LLM Profile for Composer Agent: {llm_profile_name}", style="dim")

def create_composer_flow(agent_config, terminal_app_instance):
    """
    Factory function to create an instance of the ComposerAgentFlow.
    """
    return ComposerAgentFlow(agent_config, terminal_app_instance)