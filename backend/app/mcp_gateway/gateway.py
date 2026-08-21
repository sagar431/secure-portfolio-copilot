from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ValidationError

from app.mcp_gateway.contracts import (
    APPROVED_TOOL_NAMES,
    ApprovedToolName,
    GatewayReasonCode,
    GetDocumentExcerptInput,
    PermittedToolDescriptor,
    PermittedToolInputField,
    PermittedToolInputSchema,
    SearchAuthorizedDocumentsInput,
    StructuredToolObservation,
    ToolPayload,
)
from app.mcp_gateway.errors import (
    GatewayConfigurationError,
    ToolAdapterError,
    ToolAuthorizationError,
)
from app.models.identity import Capability
from app.policies.models import AuthorizationScope


def _json_default(value: object) -> str:
    if isinstance(value, UUID):
        return str(value)
    raise TypeError("Gateway arguments must be JSON compatible")


class ApprovedToolAdapter(Protocol):
    name: ApprovedToolName
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    required_capability: Capability

    async def invoke(
        self,
        *,
        arguments: BaseModel,
        authorization_scope: AuthorizationScope,
        request_id: str,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class ToolManifestEntry:
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    required_capability: Capability
    purpose: str
    safe_result_description: str


TOOL_MANIFEST: Mapping[ApprovedToolName, ToolManifestEntry] = {
    ApprovedToolName.SEARCH_AUTHORIZED_DOCUMENTS: ToolManifestEntry(
        input_model=SearchAuthorizedDocumentsInput,
        output_model=ToolPayload,
        required_capability=Capability.QUERY_DOCUMENTS,
        purpose="Search authorized portfolio documents for evidence relevant to one bounded query.",
        safe_result_description="Authorized evidence excerpts with host-owned document provenance.",
    ),
    ApprovedToolName.GET_DOCUMENT_EXCERPT: ToolManifestEntry(
        input_model=GetDocumentExcerptInput,
        output_model=ToolPayload,
        required_capability=Capability.QUERY_DOCUMENTS,
        purpose="Retrieve one authorized excerpt using a known document and chunk identifier.",
        safe_result_description=(
            "One authorized evidence excerpt with host-owned source provenance."
        ),
    ),
}


class ApprovedToolGateway:
    """Static, fail-closed boundary between model-selected actions and trusted adapters."""

    def __init__(
        self,
        adapters: Sequence[ApprovedToolAdapter],
        *,
        timeout_seconds: float = 3.0,
        max_transient_retries: int = 1,
    ) -> None:
        if timeout_seconds <= 0 or max_transient_retries not in {0, 1}:
            raise GatewayConfigurationError("INVALID_GATEWAY_LIMITS")
        by_name: dict[ApprovedToolName, ApprovedToolAdapter] = {}
        for adapter in adapters:
            if not isinstance(adapter.name, ApprovedToolName):
                raise GatewayConfigurationError("UNAPPROVED_TOOL_NAMESPACE")
            if adapter.name.value not in APPROVED_TOOL_NAMES:
                raise GatewayConfigurationError("UNAPPROVED_TOOL_NAMESPACE")
            if adapter.name in by_name:
                raise GatewayConfigurationError("DUPLICATE_TOOL_NAME")
            expected = TOOL_MANIFEST[adapter.name]
            if adapter.input_model.model_json_schema() != expected.input_model.model_json_schema():
                raise GatewayConfigurationError("INPUT_SCHEMA_MISMATCH")
            if (
                adapter.output_model.model_json_schema()
                != expected.output_model.model_json_schema()
            ):
                raise GatewayConfigurationError("OUTPUT_SCHEMA_MISMATCH")
            if adapter.required_capability != expected.required_capability:
                raise GatewayConfigurationError("CAPABILITY_MISMATCH")
            by_name[adapter.name] = adapter
        if set(by_name) != set(TOOL_MANIFEST):
            raise GatewayConfigurationError("TOOL_CATALOG_INCOMPLETE")
        self._adapters = by_name
        self._timeout_seconds = timeout_seconds
        self._max_transient_retries = max_transient_retries

    @staticmethod
    def authorized_catalog(
        authorization_scope: AuthorizationScope,
        permitted_tools: frozenset[str],
    ) -> tuple[ApprovedToolName, ...]:
        """Return a deterministic host-filtered catalog; it is never model-discovered."""
        capabilities = {
            capability for grant in authorization_scope.grants for capability in grant.capabilities
        }
        return tuple(
            name
            for name, entry in TOOL_MANIFEST.items()
            if name.value in permitted_tools and entry.required_capability in capabilities
        )

    @classmethod
    def permitted_catalog(
        cls,
        authorization_scope: AuthorizationScope,
        permitted_tools: frozenset[str],
    ) -> tuple[PermittedToolDescriptor, ...]:
        """Return only sanitized manifest data for Decision prompt construction."""
        descriptors: list[PermittedToolDescriptor] = []
        for name in cls.authorized_catalog(authorization_scope, permitted_tools):
            entry = TOOL_MANIFEST[name]
            schema = entry.input_model.model_json_schema(mode="validation")
            properties = schema.get("properties", {})
            required = set(schema.get("required", ()))
            fields: list[PermittedToolInputField] = []
            if not isinstance(properties, dict):
                raise GatewayConfigurationError("INPUT_SCHEMA_MISMATCH")
            for field_name, raw_field in properties.items():
                if not isinstance(raw_field, dict):
                    raise GatewayConfigurationError("INPUT_SCHEMA_MISMATCH")
                value_type = raw_field.get("type")
                if field_name not in {
                    "query",
                    "top_k",
                    "document_id",
                    "chunk_id",
                } or value_type not in {
                    "string",
                    "integer",
                }:
                    raise GatewayConfigurationError("INPUT_SCHEMA_MISMATCH")
                fields.append(
                    PermittedToolInputField(
                        name=field_name,
                        value_type=value_type,
                        required=field_name in required,
                        minimum=raw_field.get("minimum"),
                        maximum=raw_field.get("maximum"),
                        min_length=raw_field.get("minLength"),
                        max_length=raw_field.get("maxLength"),
                        format=raw_field.get("format"),
                    )
                )
            descriptors.append(
                PermittedToolDescriptor(
                    name=name,
                    purpose=entry.purpose,
                    input_schema=PermittedToolInputSchema(fields=tuple(fields)),
                    safe_result_description=entry.safe_result_description,
                )
            )
        return tuple(descriptors)

    @staticmethod
    def _observation(
        *,
        started_at: float,
        tool_name: ApprovedToolName | None,
        status: Literal["completed", "denied", "failed"],
        reason_code: GatewayReasonCode,
        retry_count: int = 0,
        payload: ToolPayload | None = None,
    ) -> StructuredToolObservation:
        duration_ms = max(0, int((time.perf_counter() - started_at) * 1000))
        return StructuredToolObservation(
            trace_id=uuid4(),
            tool_name=tool_name,
            status=status,
            reason_code=reason_code,
            retry_count=retry_count,
            duration_ms=duration_ms,
            evidence=payload.evidence if payload is not None else (),
        )

    async def execute(
        self,
        *,
        tool_name: str,
        arguments: Mapping[str, object],
        authorization_scope: AuthorizationScope,
        permitted_tools: frozenset[str],
        request_id: str,
    ) -> StructuredToolObservation:
        """Execute one known tool. Trusted scope is never sourced from ``arguments``."""
        started_at = time.perf_counter()
        try:
            approved_name = ApprovedToolName(tool_name)
        except ValueError:
            return self._observation(
                started_at=started_at,
                tool_name=None,
                status="denied",
                reason_code=GatewayReasonCode.UNKNOWN_TOOL,
            )
        if approved_name.value not in permitted_tools:
            return self._observation(
                started_at=started_at,
                tool_name=approved_name,
                status="denied",
                reason_code=GatewayReasonCode.TOOL_NOT_SHORTLISTED,
            )
        adapter = self._adapters[approved_name]
        if not any(
            adapter.required_capability in grant.capabilities
            for grant in authorization_scope.grants
        ):
            return self._observation(
                started_at=started_at,
                tool_name=approved_name,
                status="denied",
                reason_code=GatewayReasonCode.AUTHORIZATION_DENIED,
            )
        try:
            validated_input = adapter.input_model.model_validate_json(
                json.dumps(
                    dict(arguments),
                    default=_json_default,
                ),
                strict=True,
            )
        except (TypeError, ValueError, ValidationError):
            return self._observation(
                started_at=started_at,
                tool_name=approved_name,
                status="denied",
                reason_code=GatewayReasonCode.INPUT_SCHEMA_REJECTED,
            )

        retry_count = 0
        while True:
            try:
                raw_output = await asyncio.wait_for(
                    adapter.invoke(
                        arguments=validated_input,
                        authorization_scope=authorization_scope,
                        request_id=request_id,
                    ),
                    timeout=self._timeout_seconds,
                )
                if isinstance(raw_output, BaseModel):
                    output_data = raw_output.model_dump()
                elif isinstance(raw_output, Mapping):
                    output_data = dict(raw_output)
                else:
                    return self._observation(
                        started_at=started_at,
                        tool_name=approved_name,
                        status="failed",
                        reason_code=GatewayReasonCode.OUTPUT_SCHEMA_REJECTED,
                        retry_count=retry_count,
                    )
                try:
                    payload = adapter.output_model.model_validate(output_data, strict=True)
                except (TypeError, ValidationError):
                    return self._observation(
                        started_at=started_at,
                        tool_name=approved_name,
                        status="failed",
                        reason_code=GatewayReasonCode.OUTPUT_SCHEMA_REJECTED,
                        retry_count=retry_count,
                    )
                if not isinstance(payload, ToolPayload):
                    return self._observation(
                        started_at=started_at,
                        tool_name=approved_name,
                        status="failed",
                        reason_code=GatewayReasonCode.OUTPUT_SCHEMA_REJECTED,
                        retry_count=retry_count,
                    )
                return self._observation(
                    started_at=started_at,
                    tool_name=approved_name,
                    status="completed",
                    reason_code=GatewayReasonCode.TOOL_COMPLETED,
                    retry_count=retry_count,
                    payload=payload,
                )
            except ToolAuthorizationError:
                return self._observation(
                    started_at=started_at,
                    tool_name=approved_name,
                    status="denied",
                    reason_code=GatewayReasonCode.AUTHORIZATION_DENIED,
                    retry_count=retry_count,
                )
            except TimeoutError:
                reason_code = GatewayReasonCode.TOOL_TIMEOUT
                transient = True
            except ToolAdapterError as exc:
                reason_code = exc.reason_code
                transient = exc.transient
            except Exception:
                return self._observation(
                    started_at=started_at,
                    tool_name=approved_name,
                    status="failed",
                    reason_code=GatewayReasonCode.TOOL_FAILED_SAFE,
                    retry_count=retry_count,
                )
            if transient and retry_count < self._max_transient_retries:
                retry_count += 1
                continue
            return self._observation(
                started_at=started_at,
                tool_name=approved_name,
                status="failed",
                reason_code=reason_code,
                retry_count=retry_count,
            )
