# This file makes 'pocket_commander/modes/main' a Python package.
# It will export the mode's flow.

from .main_flow import create_main_flow

def get_flow(mode_config, terminal_app_instance):
    """
    Returns an instance of the PocketFlow flow for the 'main' mode.
    """
    return create_main_flow(mode_config, terminal_app_instance)