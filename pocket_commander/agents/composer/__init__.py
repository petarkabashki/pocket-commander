# This file makes 'pocket_commander/agents/composer' a Python package.
# It will export the agent's flow.

from .composer_flow import create_composer_flow

def get_flow(agent_config, terminal_app_instance):
    """
    Returns an instance of the PocketFlow flow for the 'composer' agent.
    """
    return create_composer_flow(agent_config, terminal_app_instance)