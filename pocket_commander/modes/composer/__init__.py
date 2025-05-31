# This file makes 'pocket_commander/modes/composer' a Python package.
# It will export the mode's flow.

from .composer_flow import create_composer_flow

def get_flow(mode_config, terminal_app_instance):
    """
    Returns an instance of the PocketFlow flow for the 'composer' mode.
    """
    return create_composer_flow(mode_config, terminal_app_instance)