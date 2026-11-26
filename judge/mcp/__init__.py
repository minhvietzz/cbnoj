"""MCP (Model Context Protocol) server so teachers can drive CBNoj from AI chat clients such as Gemini.

See docs/HE-THONG.md (section "MCP") for the design. Layout:

* ``protocol``   - the ``POST /mcp`` JSON-RPC (Streamable HTTP, plain JSON replies) endpoint
* ``auth``       - bearer token (django-oauth-toolkit access token with scope ``mcp``) -> user
* ``oauth_meta`` - ``/.well-known/oauth-*`` discovery documents
* ``dcr``        - RFC 7591 dynamic client registration at ``/o/register/``
* ``registry``   - tool registry; tools live in ``judge.mcp.tools``
"""
