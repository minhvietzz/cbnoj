import json

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from judge.mcp import audit, auth, tools  # noqa: F401  (tools registers itself)
from judge.mcp.registry import Context, ToolError, call_tool, list_tools

SUPPORTED_VERSIONS = ('2025-11-25', '2025-06-18', '2025-03-26')
SERVER_INSTRUCTIONS = (
    'Đây là máy chủ MCP của CBNoj (trang luyện thi/OJ). '
    'Dùng để giáo viên đăng quiz trắc nghiệm, bài viết và bài tập code. '
    'Gọi `whoami` trước để biết tài khoản được làm gì. Mọi nội dung tạo ra mặc định ở chế độ riêng tư/nháp; '
    'hãy cho người dùng xem lại trước khi công khai.'
)

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603


def _error(msg_id, code, message):
    return {'jsonrpc': '2.0', 'id': msg_id, 'error': {'code': code, 'message': message}}


def _text_result(text, is_error=False):
    return {'content': [{'type': 'text', 'text': text}], 'isError': is_error}


def _unauthorized(request, status, code):
    response = JsonResponse({'error': code}, status=status)
    if status == 401:
        challenge = 'Bearer resource_metadata="%s"' % auth.resource_metadata_url(request)
        if code == 'invalid_token':
            challenge += ', error="invalid_token"'
        response['WWW-Authenticate'] = challenge
    else:
        response.content = json.dumps({
            'error': 'forbidden',
            'error_description': 'Tài khoản này chưa có quyền giáo viên trên CBNoj.',
        }, ensure_ascii=False).encode()
    return response


def handle_message(ctx, message):
    """Return a JSON-RPC response dict, or None for notifications / client responses."""
    if not isinstance(message, dict) or message.get('jsonrpc') != '2.0':
        return _error(None, INVALID_REQUEST, 'Invalid JSON-RPC message')
    method = message.get('method')
    if method is not None and not isinstance(method, str):
        return _error(message.get('id'), INVALID_REQUEST, 'method must be a string')
    if method is None:  # a response from the client; we never send requests, so ignore it
        return None
    msg_id = message.get('id')
    is_notification = 'id' not in message
    params = message.get('params') or {}
    if not isinstance(params, dict):
        return _error(msg_id, INVALID_PARAMS, 'params must be an object')

    if method == 'initialize':
        requested = params.get('protocolVersion')
        version = requested if requested in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
        return {'jsonrpc': '2.0', 'id': msg_id, 'result': {
            'protocolVersion': version,
            'capabilities': {'tools': {'listChanged': False}},
            'serverInfo': {'name': 'cbnoj', 'title': 'CBNoj', 'version': '1.0.0'},
            'instructions': SERVER_INSTRUCTIONS,
        }}
    if method == 'ping':
        return {'jsonrpc': '2.0', 'id': msg_id, 'result': {}}
    if method == 'tools/list':
        return {'jsonrpc': '2.0', 'id': msg_id, 'result': {'tools': list_tools(ctx)}}
    if method == 'tools/call':
        name = params.get('name')
        size = len(json.dumps(params.get('arguments') or {}, ensure_ascii=False))
        if audit.rate_limited('user%d' % ctx.user.id, getattr(ctx.request, 'mcp_rate_limit', 60)):
            audit.log_call(ctx.user, str(name), size, 'rate_limited')
            return {'jsonrpc': '2.0', 'id': msg_id, 'result': _text_result(
                'Bạn gọi quá nhiều lệnh trong một phút, hãy đợi một lát rồi thử lại.', True)}
        try:
            text = call_tool(ctx, name, params.get('arguments') or {})
            outcome, result = 'ok', _text_result(text)
        except ToolError as e:
            outcome, result = 'tool_error', _text_result(str(e), True)
        except Exception:
            audit.logger.exception('tool %s crashed', name)
            outcome, result = 'crash', _text_result('Lỗi nội bộ của máy chủ khi chạy công cụ này.', True)
        audit.log_call(ctx.user, str(name), size, outcome)
        return {'jsonrpc': '2.0', 'id': msg_id, 'result': result}
    if is_notification or method.startswith('notifications/'):
        return None
    return _error(msg_id, METHOD_NOT_FOUND, 'Method not found: %s' % method)


@csrf_exempt
def mcp_endpoint(request):
    if not auth.enabled():
        return HttpResponse(status=404)
    if request.method != 'POST':
        response = HttpResponse(status=405)
        response['Allow'] = 'POST'
        return response
    user, failure = auth.authenticate(request)
    if user is None:
        return _unauthorized(request, *failure)
    if len(request.body) > getattr(settings, 'MCP_MAX_BODY_BYTES', 1 << 20):
        return JsonResponse(_error(None, INVALID_REQUEST, 'Request too large'), status=413)
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError, RecursionError):
        return JsonResponse(_error(None, PARSE_ERROR, 'Parse error'), status=400)

    request.mcp_rate_limit = getattr(settings, 'MCP_RATE_LIMIT_PER_MINUTE', 60)
    ctx = Context(request, user)
    if isinstance(payload, list):
        replies = [r for r in (handle_message(ctx, m) for m in payload[:20]) if r is not None]
        if not replies:
            return HttpResponse(status=202)
        return JsonResponse(replies, safe=False)
    reply = handle_message(ctx, payload)
    if reply is None:
        return HttpResponse(status=202)
    return JsonResponse(reply)
