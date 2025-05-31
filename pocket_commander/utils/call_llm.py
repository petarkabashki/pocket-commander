import os
import yaml
import logging

# Configure basic logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Update load_profiles to use pocket_commander.conf.yaml file
def _load_profiles(config_path="pocketflow/conf/pocket_openskad.conf.yaml"):
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
            return config.get('llm-profiles', {}) or {}  # we fetch 'llm-profiles'
    except FileNotFoundError:
        # Try the alternative path if the primary is not found
        alt_config_path = "pocket_commander.conf.yaml"
        logger.warning(f"Profile configuration file not found at {config_path}, trying {alt_config_path}")
        try:
            with open(alt_config_path, 'r') as f:
                config = yaml.safe_load(f)
                return config.get('llm-profiles', {}) or {}
        except FileNotFoundError:
            raise FileNotFoundError(f"Profile configuration file not found at {config_path} or {alt_config_path}")
        except yaml.YAMLError as e:
            raise RuntimeError(f"Error parsing YAML file {alt_config_path}: {e}")
    except yaml.YAMLError as e:
        raise RuntimeError(f"Error parsing YAML file {config_path}: {e}")


def _get_profile(profiles, name, seen=None):
    """Resolve a profile by name, handling inheritance via 'inherits' key."""
    if seen is None:
        seen = set()
    if name in seen:
        raise ValueError(f"Cyclic inheritance detected for profile '{name}'")
    seen.add(name)

    profile = profiles.get(name)
    if profile is None:
        raise ValueError(f"Profile '{name}' not found")

    parent_name = profile.get('inherits')
    if parent_name:
        parent = _get_profile(profiles, parent_name, seen)
        merged = {**parent, **profile}
        merged.pop('inherits', None)
        return merged
    return profile


def call_llm(prompt_messages, profile_name="default", config_path="pocket_commander.conf.yaml"): # Renamed prompt to prompt_messages
    """
    Execute a prompt using the LLM configured in the specified profile.
    'prompt_messages' is expected to be a list of message dictionaries.
    """
    profiles = _load_profiles(config_path)
    profile = _get_profile(profiles, profile_name)
    logger.info(f"Using LLM profile: {profile}") # Changed print to logger.info

    provider = profile.get('provider').lower()
    api_key_name = profile.get('api_key_name')
    if not api_key_name:
        raise ValueError(f"No 'api_key_name' specified for profile '{profile_name}'")

    api_key = os.environ.get(api_key_name)
    if not api_key:
        raise EnvironmentError(f"Environment variable '{api_key_name}' not set or empty")

    api_base = profile.get('api_base')

    if provider == 'openai':        
        from openai import OpenAI
        client = OpenAI(
            api_key=api_key,
            base_url=api_base or None # Corrected parameter name
        )
        # OpenAI expects messages in the format: [{"role": "user", "content": "Hello!"}]
        response = client.chat.completions.create(
            model=profile.get('model', 'gpt-4o'),
            messages=prompt_messages # Directly use the passed messages
        )
        return response.choices[0].message.content

    elif provider == 'anthropic':
        # Note: Anthropic's SDK might have changed. This is based on older patterns.
        # For Claude 3+, the messages API is preferred: client.messages.create(...)
        from anthropic import Anthropic # Corrected client import
        client = Anthropic( # Corrected client instantiation
            api_key=api_key,
            base_url=api_base or None
        )
        # Convert messages to a single string prompt for older Anthropic SDK if needed,
        # or adapt to the new messages API.
        # For simplicity, assuming prompt_messages is a list of dicts and we need to format it.
        # This part needs to be verified against the current Anthropic SDK version being used.
        # For Claude 3 messages API:
        anthropic_messages = []
        system_prompt_content = None
        for msg in prompt_messages:
            if msg["role"] == "system":
                system_prompt_content = msg["content"] # Capture system prompt
            else:
                anthropic_messages.append({"role": msg["role"], "content": msg["content"]})
        
        response = client.messages.create(
            model=profile.get('model', 'claude-3-opus-20240229'),
            max_tokens=profile.get('max_tokens', 1024),
            system=system_prompt_content, # Pass system prompt if available
            messages=anthropic_messages
        )
        return response.content[0].text


    elif provider == 'gemini':
        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError("Please install the Google Gen AI SDK: pip install google-genai")
        
        genai.configure(api_key=api_key)
        
        transformed_contents = []
        for msg in prompt_messages:
            role = msg.get("role")
            gemini_role = "user" # Default
            if role == "system": # Gemini doesn't have a "system" role in the same way as OpenAI for multi-turn.
                                 # System instructions are often prepended to the first user message or handled via specific API params.
                                 # For simplicity here, we'll treat system as user, or it could be handled differently.
                gemini_role = "user" 
            elif role == "user":
                gemini_role = "user"
            elif role == "assistant" or role == "model" or role == "tool": # Tool responses are part of the model's turn
                gemini_role = "model"
            else:
                logger.warning(f"Unknown role '{role}' in message, defaulting to 'user' for Gemini.")
                gemini_role = "user"
            
            content_text = str(msg.get("content", ""))
            transformed_contents.append({'role': gemini_role, 'parts': [{'text': content_text}]})

        logger.debug(f"Transformed contents for Gemini: {transformed_contents}")

        model_instance = genai.GenerativeModel(profile.get('model'))

        try:
            resp = model_instance.generate_content(
                contents=transformed_contents,
            )
            
            # Robust check for candidates and content
            if not resp.candidates:
                logger.error(f"Gemini response has no candidates. Response: {resp}")
                if resp.prompt_feedback:
                    logger.error(f"Gemini prompt feedback: {resp.prompt_feedback}")
                    return f"Error: Gemini content generation failed. No candidates. Feedback: {resp.prompt_feedback}"
                return "Error: Gemini content generation failed. No candidates and no feedback."

            # If candidates exist, try to extract text
            # Assuming the first candidate is the one we want
            candidate = resp.candidates[0]
            if candidate.content and candidate.content.parts:
                return candidate.content.parts[0].text
            # Fallback if parts are not structured as expected, or if .text is a direct attribute (less likely now)
            elif hasattr(candidate, 'text'): # This might be redundant if parts is the primary way
                return candidate.text
            else:
                logger.error(f"Could not extract text from Gemini candidate. Candidate: {candidate}")
                return "Error: Could not parse Gemini candidate."

        except Exception as e:
            logger.error(f"Error during Gemini content generation: {e}", exc_info=True)
            return f"Error: Exception during Gemini call - {str(e)}"


    else:
        raise NotImplementedError(f"Provider '{provider}' is not supported.")


if __name__ == "__main__":
    # Example usage - Ensure pocket_commander.conf.yaml is in the root directory or adjust path
    # And ensure the API key (e.g., GEMINI_API_KEY) is set as an environment variable.
    
    # Test messages list
    test_messages_openai = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What's the meaning of life?"}
    ]
    test_messages_gemini = [ # Gemini expects alternating user/model roles generally
        {"role": "user", "content": "What's the meaning of life?"}
    ]

    print("--- Testing OpenAI Profile (if configured) ---")
    try:
        # Ensure 'openai_profile' exists in your conf file or use 'default' if it's OpenAI
        res_openai = call_llm(test_messages_openai, profile_name="default") 
        print(f"OpenAI Response: {res_openai}")
    except Exception as e:
        print(f"Could not test OpenAI: {e}")

    print("\n--- Testing Gemini Profile (if configured) ---")
    try:
        # Ensure 'gemini_profile' exists or 'default' is Gemini
        res_gemini = call_llm(test_messages_gemini, profile_name="default") 
        print(f"Gemini Response: {res_gemini}")
    except Exception as e:
        print(f"Could not test Gemini: {e}")

    # Example for Anthropic (ensure 'anthropic_profile' or similar exists)
    # print("\n--- Testing Anthropic Profile (if configured) ---")
    # try:
    #     res_anthropic = call_llm(test_messages_openai, profile_name="default") # Assuming default is anthropic
    #     print(f"Anthropic Response: {res_anthropic}")
    # except Exception as e:
    #     print(f"Could not test Anthropic: {e}")
