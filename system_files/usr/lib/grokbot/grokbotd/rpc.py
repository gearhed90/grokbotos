"""JSON-RPC 2.0 dispatch shared by every transport."""
from . import audit, backends, policy, schema

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
BACKEND_ERROR = -32000
PERMISSION_DENIED = -32001


class Dispatcher:
    def __init__(self, schema_doc):
        self.schema = schema_doc
        self.methods = schema_doc["methods"]
        missing = [m for m in self.methods if m != "api.methods" and m not in backends.METHODS]
        if missing:
            raise ValueError("schema methods without a backend: %s" % ", ".join(missing))

    def _api_methods(self, principal):
        return {"version": self.schema.get("version"), "methods": [
            {"name": n, "description": s.get("description"), "capability": s.get("capability"),
             "allowed": policy.allowed(principal, s.get("capability")),
             "params": s.get("params")} for n, s in sorted(self.methods.items())]}

    def handle(self, req, principal, transport):
        """req: parsed JSON (or None on parse failure). Returns a response dict."""
        if req is None:
            return _err(None, PARSE_ERROR, "parse error")
        if not isinstance(req, dict) or req.get("jsonrpc") != "2.0" or not isinstance(req.get("method"), str):
            return _err(req.get("id") if isinstance(req, dict) else None, INVALID_REQUEST, "invalid request")
        rid, method = req.get("id"), req["method"]
        spec = self.methods.get(method)
        base = {"transport": transport, "principal": principal, "method": method}
        if spec is None:
            audit.record(decision="error", error="method_not_found", **base)
            return _err(rid, METHOD_NOT_FOUND, "method not found: %s" % method)
        cap = spec.get("capability")
        if not policy.allowed(principal, cap):
            audit.record(decision="deny", capability=cap, **base)
            return _err(rid, PERMISSION_DENIED, "permission denied: %s needs %s" % (method, cap),
                        {"capability": cap})
        try:
            params = schema.validate_params(spec, req.get("params"))
        except schema.ParamError as e:
            audit.record(decision="error", error="invalid_params", **base)
            return _err(rid, INVALID_PARAMS, str(e))
        try:
            if method == "api.methods":
                result = self._api_methods(principal)
            else:
                result = backends.METHODS[method](params)
        except backends.BackendError as e:
            audit.record(decision="allow", error="backend", capability=cap, **base)
            return _err(rid, BACKEND_ERROR, str(e))
        except Exception as e:  # never kill the daemon over one call
            audit.record(decision="allow", error="internal", capability=cap, **base)
            return _err(rid, BACKEND_ERROR, "internal error: %s" % type(e).__name__)
        audit.record(decision="allow", capability=cap, **base)
        return {"jsonrpc": "2.0", "id": rid, "result": result}


def _err(rid, code, msg, data=None):
    e = {"code": code, "message": msg}
    if data is not None:
        e["data"] = data
    return {"jsonrpc": "2.0", "id": rid, "error": e}
