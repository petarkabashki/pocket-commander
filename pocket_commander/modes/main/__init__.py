# This file makes 'pocket_commander/modes/main' a Python package.
# It exports the mode's composition function as per Plan v8.3.

from .main_mode_logic import create_main_mode_logic

# The create_main_mode_logic function is imported from main_mode_logic.py.
# Its signature is: 
# create_main_mode_logic(mode_config: Dict[str, Any], app_services: AppServices) 
#     -> Tuple[ModeInputHandlerFunc, List[CommandDefinition], Optional[OnEnterHook], Optional[OnExitHook]]
#
# This __init__.py re-exports it for dynamic discovery by the application core.

__all__ = ['create_main_mode_logic']