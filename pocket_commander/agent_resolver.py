import importlib
import inspect
import logging
import os
from typing import Any, Callable, Dict, List, Optional, Type, Union

from pocket_commander.types import AgentConfig
from pocket_commander.pocketflow.base import BaseNode # For type checking Node/Flow classes

logger = logging.getLogger(__name__)

# Cache for loaded modules to avoid repeated disk I/O and imports
_module_cache: Dict[str, Any] = {}
# Cache for resolved agent targets (class or function) to speed up repeated requests for the same agent path/name
_resolved_target_cache: Dict[str, Union[Type[BaseNode], Callable[..., BaseNode]]] = {}


class AgentResolver:
    """
    Resolves agent configurations by loading Python modules and identifying
    target agent classes or composition functions based on configuration and conventions.
    """

    def _load_module_from_path(self, module_path_str: str) -> Optional[Any]:
        """
        Loads a Python module given its dot-separated path string.
        Uses a cache to avoid reloading.
        """
        if module_path_str in _module_cache:
            return _module_cache[module_path_str]
        
        try:
            module = importlib.import_module(module_path_str)
            _module_cache[module_path_str] = module
            logger.debug(f"Successfully loaded and cached module: {module_path_str}")
            return module
        except ImportError as e:
            logger.error(f"Failed to import module '{module_path_str}': {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"An unexpected error occurred while importing module '{module_path_str}': {e}", exc_info=True)
            return None

    def _resolve_target_in_module(
        self,
        module: Any,
        module_path_str: str, # For logging/caching key
        class_name: Optional[str] = None,
        composition_function_name: Optional[str] = None,
        filename_stem: Optional[str] = None # e.g., "my_agent_node" from "my_agent_node.py"
    ) -> Optional[Union[Type[BaseNode], Callable[..., BaseNode]]]:
        """
        Identifies the target class or function within a loaded module.
        Uses a cache for resolved targets.
        """
        cache_key = f"{module_path_str}:{class_name or composition_function_name or filename_stem or 'convention'}"
        if cache_key in _resolved_target_cache:
            return _resolved_target_cache[cache_key]

        target: Optional[Union[Type[BaseNode], Callable[..., BaseNode]]] = None

        # 1. Explicit composition_function_name
        if composition_function_name:
            if hasattr(module, composition_function_name):
                func_target = getattr(module, composition_function_name)
                if callable(func_target):
                    # Further validation might be needed here if we can inspect return type,
                    # but for now, assume it returns a BaseNode compatible instance.
                    target = func_target
                    logger.debug(f"Resolved target by composition_function_name: {composition_function_name} in {module_path_str}")
                else:
                    logger.warning(f"Attribute '{composition_function_name}' in module '{module_path_str}' is not callable.")
            else:
                logger.warning(f"Composition function '{composition_function_name}' not found in module '{module_path_str}'.")
        
        # 2. Explicit class_name (only if no composition function was found or specified)
        if not target and class_name:
            if hasattr(module, class_name):
                cls_target = getattr(module, class_name)
                if inspect.isclass(cls_target) and issubclass(cls_target, BaseNode):
                    target = cls_target
                    logger.debug(f"Resolved target by class_name: {class_name} in {module_path_str}")
                else:
                    logger.warning(f"Attribute '{class_name}' in module '{module_path_str}' is not a class or not a subclass of BaseNode.")
            else:
                logger.warning(f"Class '{class_name}' not found in module '{module_path_str}'.")

        # 3. Conventions (only if no explicit names found a target)
        if not target and filename_stem:
            # Convention 3.1: Class named 'Agent'
            if hasattr(module, "Agent"):
                cls_agent = getattr(module, "Agent")
                if inspect.isclass(cls_agent) and issubclass(cls_agent, BaseNode):
                    target = cls_agent
                    logger.debug(f"Resolved target by convention: class 'Agent' in {module_path_str}")
            
            # Convention 3.2: Class name matching filename (CamelCase)
            if not target:
                convention_class_name = "".join(word.capitalize() for word in filename_stem.split('_'))
                if hasattr(module, convention_class_name):
                    cls_filename_match = getattr(module, convention_class_name)
                    if inspect.isclass(cls_filename_match) and issubclass(cls_filename_match, BaseNode):
                        target = cls_filename_match
                        logger.debug(f"Resolved target by convention: class '{convention_class_name}' in {module_path_str}")

            # Convention 3.3: Flow composition function by filename
            if not target:
                convention_func_names = [
                    "create_flow", 
                    f"create_{filename_stem}_flow"
                ]
                for func_name in convention_func_names:
                    if hasattr(module, func_name):
                        func_convention = getattr(module, func_name)
                        if callable(func_convention):
                            target = func_convention
                            logger.debug(f"Resolved target by convention: function '{func_name}' in {module_path_str}")
                            break # Found one, stop checking convention functions
        
        if target:
            _resolved_target_cache[cache_key] = target
        return target

    def resolve_agent_config(
        self,
        slug: str,
        agent_yaml_config: Dict[str, Any],
        project_root: str, # Needed to resolve relative paths
        discovery_folders: Optional[List[str]] = None # For future use if path isn't fully specific
    ) -> Optional[AgentConfig]:
        """
        Resolves a raw agent YAML configuration into an AgentConfig object.
        The 'path' in agent_yaml_config is treated as a Python module path
        (e.g., "pocket_commander.core_agents.my_agent_file") rather than a filesystem path.
        Filesystem path resolution to module path needs to happen before this, or this needs adjustment.

        For now, assumes 'path' is a Python importable module string.
        """
        path_str = agent_yaml_config.get("path")
        if not path_str:
            logger.error(f"Agent '{slug}' configuration is missing 'path' (Python module path).")
            return None

        # The 'path' from YAML is assumed to be a Python module path string.
        # e.g., "pocket_commander.core_agents.main_agent" if main_agent.py is in pocket_commander/core_agents/
        # This means the directory containing "pocket_commander" (i.e., project_root) must be in PYTHONPATH.
        # Or, if path_str is like "core_agents.main_agent", then project_root/pocket_commander must be in PYTHONPATH.
        # Let's assume path_str is directly importable for now.
        
        module_path_str = path_str # This is the Python module path, not a filesystem path.
        
        # Extract filename stem for convention-based resolution
        # e.g., from "pocket_commander.core_agents.my_agent_node", stem is "my_agent_node"
        filename_stem = module_path_str.split('.')[-1] if '.' in module_path_str else module_path_str


        module = self._load_module_from_path(module_path_str)
        if not module:
            return None

        class_name_cfg = agent_yaml_config.get("class_name")
        comp_func_name_cfg = agent_yaml_config.get("composition_function_name")

        resolved_target = self._resolve_target_in_module(
            module,
            module_path_str,
            class_name_cfg,
            comp_func_name_cfg,
            filename_stem
        )

        if not resolved_target:
            logger.error(f"Could not resolve target class or function for agent '{slug}' in module '{module_path_str}'.")
            return None

        is_class = inspect.isclass(resolved_target)
        
        # Create AgentConfig instance
        # The actual filesystem path might need to be stored differently if 'path_str' is purely a module path.
        # For now, let's assume 'path_str' can also serve as an identifier or is derived from a fs path.
        # A more robust solution would involve converting file system paths from discovery_folders
        # into module paths. The current `path_str` in YAML is defined as "Path to the agent's Python file".
        # This implies it should be a module path that Python can import.

        # For `AgentConfig.path`, we should store the Python module path used for import.
        agent_config_instance = AgentConfig(
            slug=slug,
            path=module_path_str, # Storing the Python module path
            description=agent_yaml_config.get("description"),
            target_class=resolved_target if is_class else None,
            target_composition_function=resolved_target if not is_class else None,
            is_class_target=is_class,
            init_args=agent_yaml_config.get("init_args", {}),
            raw_config=agent_yaml_config
        )
        logger.info(f"Successfully resolved agent '{slug}': target_type={'class' if is_class else 'function'}, target_name='{resolved_target.__name__}'")
        return agent_config_instance

# Example usage (for testing or integration into config_loader.py)
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    resolver = AgentResolver()

    # Mock project structure for testing:
    # project_root/
    #   pocket_commander/
    #     core_agents/
    #       __init__.py
    #       my_mock_agent.py
    #     types.py (with AgentConfig, BaseNode - BaseNode might be mocked or properly pathed)
    #     pocketflow/
    #        base.py (with BaseNode)
    
    # Create mock files for testing
    mock_project_root = "_test_mock_project"
    core_agents_dir = os.path.join(mock_project_root, "pocket_commander", "core_agents")
    pocketflow_dir = os.path.join(mock_project_root, "pocket_commander", "pocketflow")

    os.makedirs(core_agents_dir, exist_ok=True)
    os.makedirs(pocketflow_dir, exist_ok=True)

    with open(os.path.join(core_agents_dir, "__init__.py"), "w") as f:
        f.write("")
    with open(os.path.join(pocketflow_dir, "__init__.py"), "w") as f:
        f.write("")
    
    # Mock BaseNode for testing if not easily importable
    base_node_content = """
class BaseNode:
    def __init__(self, *args, **kwargs): self.params = kwargs
    def set_params(self, params): self.params = params
"""
    with open(os.path.join(pocketflow_dir, "base.py"), "w") as f:
        f.write(base_node_content)

    mock_agent_content = """
from pocket_commander.pocketflow.base import BaseNode

class MyMockAgentNode(BaseNode): # Filename match convention
    def __init__(self, greeting="Hello from MyMockAgentNode", **kwargs):
        super().__init__(**kwargs)
        self.greeting = greeting
        print(f"MyMockAgentNode initialized with: {greeting}, other_args: {self.params}")

class Agent(BaseNode): # 'Agent' convention
    def __init__(self, special_val=42, **kwargs):
        super().__init__(**kwargs)
        self.special_val = special_val
        print(f"Agent (class) initialized with: {special_val}, other_args: {self.params}")

def create_my_mock_agent_flow(app_services, init_args): # Filename func convention
    print(f"create_my_mock_agent_flow called with app_services, init_args: {init_args}")
    # In a real scenario, this would return an instantiated Flow object
    class MockFlow(BaseNode):
        def __init__(self): super().__init__(); print("MockFlow from function initialized")
    return MockFlow()

def custom_composer(app_services, init_args): # Explicit func name
    print(f"custom_composer called with app_services, init_args: {init_args}")
    class ComposedFlow(BaseNode):
        def __init__(self): super().__init__(); print("ComposedFlow from custom_composer initialized")
    return ComposedFlow()
"""
    with open(os.path.join(core_agents_dir, "my_mock_agent.py"), "w") as f:
        f.write(mock_agent_content)

    # Add mock_project_root to sys.path for imports to work
    import sys
    sys.path.insert(0, os.path.abspath(mock_project_root))
    
    print(f"sys.path modified: {sys.path[0]}")
    print(f"Current working directory: {os.getcwd()}")
    print(f"Checking existence of mock file: {os.path.exists(os.path.join(core_agents_dir, 'my_mock_agent.py'))}")


    test_configs = {
        "agent_by_class_name": {
            "path": "pocket_commander.core_agents.my_mock_agent",
            "class_name": "MyMockAgentNode",
            "description": "Test agent resolved by explicit class name.",
            "init_args": {"greeting": "Custom Greeting", "llm_profile": "test_dev"}
        },
        "agent_by_convention_agent_class": {
            "path": "pocket_commander.core_agents.my_mock_agent",
            "description": "Test agent resolved by 'Agent' class convention.",
            "init_args": {"special_val": 100}
        },
        "agent_by_convention_filename_class": { # This will be shadowed by 'Agent' class if 'Agent' exists
            "path": "pocket_commander.core_agents.my_mock_agent",
            "description": "Test agent by filename class convention (MyMockAgentNode).",
             # To test this specifically, 'Agent' class would need to be removed or class_name specified
        },
        "agent_by_convention_filename_func": {
            "path": "pocket_commander.core_agents.my_mock_agent",
            "description": "Test agent by filename func convention (create_my_mock_agent_flow)."
            # This would be chosen if 'Agent' and 'MyMockAgentNode' classes were not present or named differently.
        },
        "agent_by_comp_func_name": {
            "path": "pocket_commander.core_agents.my_mock_agent",
            "composition_function_name": "custom_composer",
            "description": "Test agent by explicit composition function name.",
            "init_args": {"flow_param": "example_value"}
        },
        "agent_missing_path": {
            "description": "Test agent with missing path."
        },
        "agent_bad_path": {
            "path": "pocket_commander.core_agents.non_existent_agent",
            "description": "Test agent with a non-existent module path."
        },
        "agent_bad_class_name": {
            "path": "pocket_commander.core_agents.my_mock_agent",
            "class_name": "NonExistentClass",
            "description": "Test agent with a non-existent class name."
        }
    }

    # Test resolution
    # Note: For convention tests, the order of definition in the mock file and resolver logic matters.
    # The current resolver prioritizes explicit names, then 'Agent' class, then filename class, then filename func.

    print("\n--- Testing Agent Resolution ---")
    resolved_agent_configs = {}
    for slug, conf in test_configs.items():
        print(f"\nAttempting to resolve agent: {slug}")
        # For this test, project_root is not strictly used by resolve_agent_config as path is module path
        # but good to pass for completeness if logic changes.
        resolved_conf = resolver.resolve_agent_config(slug, conf, mock_project_root)
        if resolved_conf:
            resolved_agent_configs[slug] = resolved_conf
            print(f"Resolved {slug}: Target type: {'Class' if resolved_conf.is_class_target else 'Function'}, Name: {resolved_conf.target_class.__name__ if resolved_conf.target_class else resolved_conf.target_composition_function.__name__}")
            # Example instantiation (simplified)
            if resolved_conf.target_class:
                print(f"  Mock instantiating class with init_args: {resolved_conf.init_args}")
                # instance = resolved_conf.target_class(**resolved_conf.init_args)
            elif resolved_conf.target_composition_function:
                print(f"  Mock calling function with init_args: {resolved_conf.init_args}")
                # instance = resolved_conf.target_composition_function(None, resolved_conf.init_args) # Mock AppServices
        else:
            print(f"Failed to resolve agent: {slug}")
            
    # Cleanup mock directory (optional)
    # import shutil
    # shutil.rmtree(mock_project_root)
    # sys.path.pop(0)
    print("\n--- Agent Resolution Test Complete ---")