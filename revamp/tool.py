from collections.abc import Generator
from typing import Any
from uuid import UUID

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from revamp import client


def text(parameters: dict, name: str, maximum: int, required: bool = True) -> str:
    value = parameters.get(name, "")
    if value is None and not required:
        return ""
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise client.RevampError(f"Please provide a valid {name} (up to {maximum} characters).")
    return value.strip()


def identifier(parameters: dict, name: str, required: bool = True) -> str:
    value = text(parameters, name, 36, required)
    if value:
        try:
            return str(UUID(value))
        except ValueError:
            raise client.RevampError(f"Please provide a valid {name} from Revamp.") from None
    return value


class RevampTool(Tool):
    operation: str

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        token = self.runtime.credentials.get("access_token")
        if not isinstance(token, str) or not token:
            raise client.RevampError("Please connect your Revamp account.")
        operation = self.operation
        arguments: dict[str, Any] = {}
        if operation.startswith("start_"):
            arguments["name"] = text(tool_parameters, "name", 120)
            arguments["brief"] = text(tool_parameters, "brief", 2000, operation != "start_website_redesign")
            folder = identifier(tool_parameters, "clientId", False)
            if folder:
                arguments["clientId"] = folder
            if operation == "start_website_redesign":
                # Revamp owns public-URL validation and inspection. This adapter
                # never fetches the requested website itself.
                arguments["url"] = text(tool_parameters, "url", 2048)
        elif operation in ("check_project", "refine_project"):
            arguments["projectId"] = identifier(tool_parameters, "projectId")
            if operation == "check_project":
                submission = text(tool_parameters, "submissionId", 256, False)
                if submission:
                    arguments["submissionId"] = submission
            else:
                arguments["instruction"] = text(tool_parameters, "instruction", 4000)
        if operation.startswith("start_") or operation == "refine_project":
            reference = text(tool_parameters, "requestReference", 200)
            arguments["requestId"] = client.stable_request_id(client.account_id(token), operation,
                                                              reference, arguments.get("projectId", ""))
        result = client.call_tool(token, operation, arguments)
        yield self.create_json_message(result)
        for name, value in result.items():
            yield self.create_variable_message(name, value)
