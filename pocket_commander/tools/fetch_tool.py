# %%
"""
Tool for fetching content from a URL.
"""
import httpx
import markdownify
import protego
import readabilipy.simple_json
from urllib.parse import urlparse, urlunparse

from pocket_commander.tools.decorators import tool
from pocket_commander.tools.definition import ToolDefinition, ToolParameterDefinition
from pocket_commander.tools.registry import global_tool_registry

DEFAULT_USER_AGENT_AUTONOMOUS = "AgentContextProtocol/1.0 (Autonomous; +https://github.com/modelcontextprotocol/servers)"

async def _check_may_autonomously_fetch_url(url: str, user_agent: str) -> None:
    """
    Check if the URL can be fetched by the user agent according to the robots.txt file.
    Raises a ValueError if not.
    """
    robot_txt_url = get_robots_txt_url(url)

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                robot_txt_url,
                follow_redirects=True,
                headers={"User-Agent": user_agent},
            )
        except httpx.HTTPError as e:
            raise ValueError(
                f"Failed to fetch robots.txt {robot_txt_url} due to a connection issue: {e}"
            )
        if response.status_code in (401, 403):
            raise ValueError(
                f"When fetching robots.txt ({robot_txt_url}), received status {response.status_code} "
                f"so assuming that autonomous fetching is not allowed."
            )
        elif 400 <= response.status_code < 500:
            # If robots.txt not found, assume allowed
            return
        robot_txt = response.text
    
    # Remove comments from robots.txt for Protego
    processed_robot_txt = "\n".join(
        line for line in robot_txt.splitlines() if not line.strip().startswith("#")
    )
    robot_parser = protego.Protego.parse(processed_robot_txt)
    if not robot_parser.can_fetch(str(url), user_agent):
        raise ValueError(
            f"The site's robots.txt ({robot_txt_url}) specifies that autonomous fetching of this page is not allowed for user agent '{user_agent}'."
        )

def get_robots_txt_url(url: str) -> str:
    """Get the robots.txt URL for a given website URL.

    Args:
        url: Website URL to get robots.txt for

    Returns:
        URL of the robots.txt file
    """
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, "/robots.txt", "", "", ""))

def _extract_content_from_html(html: str) -> str:
    """Extract and convert HTML content to Markdown format.

    Args:
        html: Raw HTML content to process

    Returns:
        Simplified markdown version of the content
    """
    ret = readabilipy.simple_json.simple_json_from_html_string(
        html, use_readability=True
    )
    if not ret["content"]:
        return "<error>Page failed to be simplified from HTML</error>"
    content = markdownify.markdownify(
        ret["content"],
        heading_style=markdownify.ATX,
    )
    return content

@tool
async def fetch(
    url: str,
    max_length: int = 5000,
    start_index: int = 0,
    raw: bool = False,
    # ignore_robots_txt: bool = False, # Future consideration
    user_agent: str = DEFAULT_USER_AGENT_AUTONOMOUS,
) -> str:
    """
    Fetches content from a given URL. It can access the internet.

    This tool respects robots.txt by default. If the content is HTML and 'raw' is false,
    it will attempt to simplify the HTML into Markdown.
    """
    # if not ignore_robots_txt: # Future consideration
    try:
        await _check_may_autonomously_fetch_url(url, user_agent)
    except ValueError as e:
        return f"<error>Could not fetch URL due to robots.txt restriction or error: {e}</error>"

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                url,
                follow_redirects=True,
                headers={"User-Agent": user_agent},
                timeout=30,
            )
            response.raise_for_status()  # Raise an exception for bad status codes
        except httpx.HTTPStatusError as e:
            return f"<error>Failed to fetch {url} - status code {e.response.status_code}: {e.response.reason_phrase}</error>"
        except httpx.HTTPError as e:
            return f"<error>Failed to fetch {url}: {e!r}</error>"

        fetched_content = response.text

    content_type = response.headers.get("content-type", "")
    is_html = "text/html" in content_type.lower() or "<html" in fetched_content[:100].lower()

    if is_html and not raw:
        processed_content = _extract_content_from_html(fetched_content)
    else:
        processed_content = fetched_content
    
    content_len = len(processed_content)
    
    if start_index >= content_len:
        return f"<error>Start index ({start_index}) is beyond the end of the content (length {content_len}).</error>"

    end_index = start_index + max_length
    truncated_content = processed_content[start_index:end_index]
    
    prefix = f"Contents of {url}:\n"
    if start_index > 0:
        prefix += f"(Content starts at index {start_index})\n"
    
    suffix = ""
    if end_index < content_len:
        suffix = f"\n<error>Content truncated. Call the fetch tool with a start_index of {end_index} to get more content.</error>"
        
    return prefix + truncated_content + suffix

FETCH_TOOL_DEFINITION = ToolDefinition(
    name="fetch",
    description="Fetches content from a given URL. It can access the internet. Respects robots.txt and can simplify HTML to Markdown.",
    parameters=[
        ToolParameterDefinition(
            name="url",
            param_type=str,
            type_str="string",
            description="The URL to fetch content from.",
            is_required=True,
        ),
        ToolParameterDefinition(
            name="max_length",
            param_type=int,
            type_str="integer",
            description="Maximum number of characters to return. Default is 5000.",
            is_required=False,
            default_value=5000,
        ),
        ToolParameterDefinition(
            name="start_index",
            param_type=int,
            type_str="integer",
            description="Character index to start returning content from. Default is 0.",
            is_required=False,
            default_value=0,
        ),
        ToolParameterDefinition(
            name="raw",
            param_type=bool,
            type_str="boolean",
            description="If True, returns the raw content without attempting to simplify HTML to Markdown. Default is False.",
            is_required=False,
            default_value=False,
        ),
        ToolParameterDefinition(
            name="user_agent",
            param_type=str,
            type_str="string",
            description=f"The User-Agent string to use for the request. Defaults to '{DEFAULT_USER_AGENT_AUTONOMOUS}'.",
            is_required=False,
            default_value=DEFAULT_USER_AGENT_AUTONOMOUS,
        ),
    ],
    func=fetch,
)

# The @tool decorator handles registration with the global_tool_registry
# For explicitness and to ensure the definition is available if needed elsewhere:
if not global_tool_registry.get_tool("fetch"):
    global_tool_registry.register_tool_definition(FETCH_TOOL_DEFINITION)

# %%