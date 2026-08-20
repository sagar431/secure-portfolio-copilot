from app.mcp_gateway.contracts import GatewayReasonCode


class GatewayConfigurationError(RuntimeError):
    """Fail-closed startup error that contains a reason code, never tool content."""


class ToolAdapterError(RuntimeError):
    def __init__(self, reason_code: GatewayReasonCode, *, transient: bool = False) -> None:
        super().__init__("Approved tool execution failed safely.")
        self.reason_code = reason_code
        self.transient = transient


class ToolAuthorizationError(ToolAdapterError):
    def __init__(self) -> None:
        super().__init__(GatewayReasonCode.AUTHORIZATION_DENIED)


class ToolTransientError(ToolAdapterError):
    def __init__(self) -> None:
        super().__init__(GatewayReasonCode.TOOL_TRANSIENT_FAILURE, transient=True)
