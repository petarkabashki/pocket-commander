# Project Plan: Abstract AgUIClient and Terminal Implementation

**Overall Goal:** To architect a modular UI interaction system by creating an abstract `AgUIClient` that communicates with agents via the `AsyncEventBus` using `ag_ui` events, and then implement a concrete `TerminalAgUIClient` to replace the current terminal interaction mechanism.

---

**Phase 1: Define `AbstractAgUIClient` and Core Event Structures**

1.  **Define `AppInputEvent`:**
    *   **File:** `pocket_commander/events.py`
    *   **Action:** Add the following class definition and include it in `__all__`.
        ```python
        # Add to pocket_commander/events.py
        import uuid # Add this import if not present
        from pydantic import Field # Add this import if not present
        from typing import Optional # Add this import if not present
        # Assuming BaseEvent is the one from pocket_commander.event_bus

        class AppInputEvent(BaseEvent):
            """
            Event published by a UI client when the user submits input
            intended for the application or an agent.
            """
            input_text: str
            source_ui_client_id: Optional[str] = None # e.g., "terminal", "web_ui_session_xyz"
            event_id: str = Field(default_factory=lambda: str(uuid.uuid4())) # Added for better tracking
        ```
    *   **Rationale:** This event will be the primary way UI clients send user commands/messages into the application core. `event_id` added for uniqueness.

2.  **Create `AbstractAgUIClient` (ABC):**
    *   **File:** `pocket_commander/ag_ui/client.py` (New file)
    *   **Contents:**
        ```python
        from abc import ABC, abstractmethod
        from typing import Any, Optional
        import uuid # For generating message IDs

        from pocket_commander.types import AppServices
        from pocket_commander.event_bus import AsyncEventBus
        from pocket_commander.ag_ui import events as ag_ui_events
        # from pocket_commander.ag_ui.types import Message # Not directly used now
        from pocket_commander.events import AppInputEvent # Ensure this is the newly defined one

        class AbstractAgUIClient(ABC):
            def __init__(self, app_services: AppServices, client_id: str = "default_ui_client"):
                self.app_services: AppServices = app_services
                self.event_bus: AsyncEventBus = app_services.event_bus
                self.client_id: str = client_id

            @abstractmethod
            async def initialize(self) -> None:
                """Initializes the client, subscribes to necessary events."""
                pass

            @abstractmethod
            async def start(self) -> None:
                """Starts the client's main interaction loop."""
                pass

            @abstractmethod
            async def stop(self) -> None:
                """Stops the client and cleans up resources."""
                pass

            @abstractmethod
            async def handle_ag_ui_event(self, event: ag_ui_events.Event) -> None:
                """
                Processes and renders an ag_ui event from the agent/system.
                This method will likely be called by specific event handlers
                registered with the event bus by the concrete client.
                """
                pass

            async def send_app_input(self, raw_input: str) -> None:
                """Sends user input to the application core/agents."""
                event = AppInputEvent(
                    input_text=raw_input,
                    source_ui_client_id=self.client_id
                )
                await self.event_bus.publish(event)
                # Also publish the user's input as ag_ui message events for history
                await self._publish_user_message_as_ag_ui_events(raw_input)

            async def _publish_user_message_as_ag_ui_events(self, user_input: str) -> None:
                """
                Helper to publish user input as a series of ag_ui text events
                (TextMessageStart, TextMessageContent, TextMessageEnd) with role 'user'.
                """
                message_id = str(uuid.uuid4())
                
                start_event = ag_ui_events.TextMessageStartEvent(
                    message_id=message_id,
                    role="user" # type: ignore # Pydantic literal validation handles this
                )
                await self.event_bus.publish(start_event)

                if user_input: # Ensure delta is not empty for TextMessageContentEvent
                    content_event = ag_ui_events.TextMessageContentEvent(
                        message_id=message_id,
                        delta=user_input
                    )
                    await self.event_bus.publish(content_event)

                end_event = ag_ui_events.TextMessageEndEvent(
                    message_id=message_id
                )
                await self.event_bus.publish(end_event)

            @abstractmethod
            async def request_dedicated_input(self, prompt_message: str, is_sensitive: bool = False) -> str:
                """Requests a single line of dedicated input from the user."""
                pass
        ```
    *   **Rationale:** Defines the common interface for any UI client.

---

**Phase 2: Implement `TerminalAgUIClient`**

1.  **Create `TerminalAgUIClient` Class:**
    *   **File:** `pocket_commander/ag_ui/terminal_client.py` (New file)
    *   **Inheritance:** `AbstractAgUIClient`
    *   **Core Logic:**
        *   Adapt constructor, `prompt-toolkit.PromptSession`, `rich.Console`, and buffer management (`_message_buffers`, `_tool_call_args_buffers`, etc.) from the current `TerminalInteractionFlow`.
        *   **`initialize()`**:
            *   Call `super().initialize()` if any base class init logic is added.
            *   Subscribe to all relevant `ag_ui.events` (e.g., `TextMessageStartEvent`, `TextMessageContentEvent`, `TextMessageEndEvent`, `ToolCallStartEvent`, `ToolCallArgsEvent`, `ToolCallEndEvent`, `RunErrorEvent`, `StepStartedEvent`, `StepFinishedEvent`).
            *   Each subscription should point to a dedicated handler method within `TerminalAgUIClient` (e.g., `self._handle_text_message_start`). These handlers will implement the `self.console.print(...)` logic.
            *   Subscribe to the internal `RequestPromptEvent` (from `pocket_commander.events`) and link to `_handle_request_prompt_event`.
        *   **`handle_ag_ui_event()`**: This abstract method might not be directly called if specific handlers are registered with the event bus. Alternatively, the event bus subscription can call this, and it can then delegate based on `event.type`. The former (direct handlers) is often cleaner.
        *   **`start()`**: Initialize `prompt-toolkit` session, `rich.Console`. Call `await self.initialize()`. Run `_main_loop()`.
        *   **`stop()`**: Clean up resources, cancel tasks (e.g., `_prompt_handler_task`).
        *   **`_main_loop()`**: Adapted from `TerminalInteractionFlow._main_loop()`. On user input from `self.session.prompt_async()`, call `await self.send_app_input(user_input_str)`. Handle `KeyboardInterrupt`, `EOFError`.
        *   **Dedicated Input:**
            *   Implement `request_dedicated_input`: This method might internally use a future and an event, or directly manage the prompt session if called from within the `_main_loop`'s context. The `TerminalInteractionFlow`'s pattern of publishing `RequestPromptEvent` and awaiting a `PromptResponseEvent` (or a future linked to it) is a good decoupled approach.
            *   `_handle_request_prompt_event`: Sets up for capturing the next input as a response to a dedicated prompt.
        *   **Rendering:** Port all `self.console.print` logic, styling (e.g., `_get_style_for_role`), and message/tool call argument buffering from `TerminalInteractionFlow`'s event handlers into the new client's respective handlers.
        *   **Completer:** Integrate `AppStateAwareCompleter` (from `TerminalInteractionFlow`) into the `prompt_async` call.

---

**Phase 3: Integrate `TerminalAgUIClient` into `app_core.py`**

1.  **Modify `pocket_commander/app_core.py`:**
    *   Remove instantiation and management of `TerminalInteractionFlow`.
    *   In `AppCore.__init__` or an initialization method:
        *   Instantiate `self.ui_client = TerminalAgUIClient(self.app_services, client_id="terminal_main")`.
    *   In `AppCore.start_services()` (or equivalent): Call `await self.ui_client.start()`. This might need to be run as a separate task if `ui_client.start()` is blocking.
    *   In `AppCore.stop_services()` (or equivalent): Call `await self.ui_client.stop()`.
    *   **Input Handling:**
        *   Subscribe `AppCore` to `AppInputEvent`.
        *   The handler method for `AppInputEvent` (e.g., `async def _handle_app_input(self, event: AppInputEvent)`) will:
            *   Check `event.source_ui_client_id` if multiple UI clients are anticipated.
            *   Perform initial input parsing for global commands (e.g., `/agent`, `/exit`, `/help`) using `TerminalCommandInput(event.input_text)`.
            *   If not a global command, dispatch the `event.input_text` (or the `TerminalCommandInput` object) to the active agent. This replaces the old `process_input_callback` logic. The mechanism for dispatching to the active agent (e.g., via another internal event, or direct method call on an agent manager) should be clarified based on current `app_core` structure.

---

**Phase 4: Refactor and Cleanup**

1.  **Remove Obsolete Code:** Delete `pocket_commander/flows/terminal_interaction_flow.py`.
2.  **Update Imports:** Adjust imports throughout the codebase to point to the new client and event definitions.
3.  **Review `pocket_commander/commands/terminal_io.py`:**
    *   `TerminalCommandInput` likely remains useful in `app_core`'s `AppInputEvent` handler for parsing.
    *   `TerminalOutputHandler`'s role needs re-evaluation. If all output is via `ag_ui` events rendered by `TerminalAgUIClient`, it might become obsolete or its responsibilities significantly reduced.
4.  **Documentation:**
    *   Update `cline_docs` (especially `systemPatterns.md`, `activeContext.md`, `progress.md`) to reflect the new UI client architecture.
    *   Update any other relevant developer documentation (e.g., `docs/pocketflow-guides.md` if UI interaction patterns are discussed).

---

**Mermaid Diagram of Proposed Architecture:**

```mermaid
graph TD
    subgraph UI Layer
        TerminalClient[TerminalAgUIClient]
        TerminalClient -- Manages --> PromptToolkit[prompt-toolkit Session]
        TerminalClient -- Manages --> RichConsole[rich.Console]
        PromptToolkit -- Raw User Input --> TerminalClient
    end

    subgraph Event Bus / Communication
        EventBus[AsyncEventBus]
    end

    subgraph Application Logic
        AppCore[app_core.py]
        AgentManager[Agent Manager / Active Agent]
    end

    TerminalClient -- Publishes AppInputEvent --> EventBus
    TerminalClient -- Publishes ag_ui.UserMessage Events --> EventBus
    EventBus -- Delivers AppInputEvent --> AppCore

    AppCore -- Processes Input / Dispatches to --> AgentManager
    AgentManager -- Produces Output --> AgentOutputEvents((ag_ui.Events Stream))
    AgentOutputEvents -- Publishes to --> EventBus

    EventBus -- Delivers ag_ui.Events Stream --> TerminalClient
    TerminalClient -- Renders via RichConsole --> UserView[User's Terminal]

    %% Dedicated Prompts
    InternalLogicOrAgent[Agent/Internal Logic] -- Publishes RequestPromptEvent --> EventBus
    EventBus -- Delivers RequestPromptEvent --> TerminalClient
    TerminalClient -- Prompts User via PromptToolkit --> UserView
    UserView -- Dedicated Input --> PromptToolkit
    PromptToolkit -- Dedicated Input --> TerminalClient
    TerminalClient -- Publishes PromptResponseEvent --> EventBus
    EventBus -- Delivers PromptResponseEvent --> InternalLogicOrAgent


    style EventBus fill:#f9f,stroke:#333,stroke-width:2px
    style TerminalClient fill:#ccf,stroke:#333,stroke-width:2px
    style AppCore fill:#cfc,stroke:#333,stroke-width:2px