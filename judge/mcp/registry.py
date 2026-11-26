"""Tool registry. A tool is a function ``handler(ctx, **arguments) -> jsonable`` registered with ``@tool``."""
import json

TOOLS = {}


class ToolError(Exception):
    """A problem the model/teacher can fix (bad syntax, no permission...). The message is shown to the model."""


class Context(object):
    def __init__(self, request, user):
        self.request = request
        self.user = user
        self.profile = user.profile


def tool(name, description, properties=None, required=(), read_only=False, destructive=False, idempotent=False,
         enabled=None):
    """`enabled` (optional) is a no-argument callable; the tool is hidden and refused while it returns False."""
    def wrapper(handler):
        TOOLS[name] = {
            'handler': handler,
            'enabled': enabled,
            'definition': {
                'name': name,
                'description': description,
                'inputSchema': {
                    'type': 'object',
                    'properties': properties or {},
                    'required': list(required),
                    'additionalProperties': False,
                },
                'annotations': {
                    'readOnlyHint': read_only,
                    'destructiveHint': destructive,
                    'idempotentHint': idempotent,
                    'openWorldHint': False,
                },
            },
        }
        return handler
    return wrapper


def list_tools(ctx):
    return [t['definition'] for t in TOOLS.values() if t['enabled'] is None or t['enabled']()]


def call_tool(ctx, name, arguments):
    entry = TOOLS.get(name)
    if entry is None or (entry['enabled'] is not None and not entry['enabled']()):
        raise ToolError('Không có công cụ tên "%s".' % name)
    if not isinstance(arguments, dict):
        raise ToolError('Tham số phải là một đối tượng JSON.')
    schema = entry['definition']['inputSchema']
    unknown = sorted(set(arguments) - set(schema['properties']))
    if unknown:
        raise ToolError('Tham số không hợp lệ: %s.' % ', '.join(unknown))
    missing = [r for r in schema['required'] if arguments.get(r) in (None, '')]
    if missing:
        raise ToolError('Thiếu tham số bắt buộc: %s.' % ', '.join(missing))
    result = entry['handler'](ctx, **arguments)
    return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2)
