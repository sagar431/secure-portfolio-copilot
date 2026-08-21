from app.chat.contracts import (
    GroundedGenerationRequest,
    LLMErrorCode,
    LLMGeneration,
    LLMProvider,
    LLMProviderError,
    LLMUsage,
)
from app.model_routing import (
    ModelRoute,
    RouteReason,
    RoutingSignals,
    WorkloadKind,
    route_model,
)


class DeterministicRoutingLLMProvider:
    model_name = "deterministic-router"

    def __init__(
        self,
        *,
        simple: LLMProvider,
        heavy: LLMProvider,
        heavy_fallback: LLMProvider,
        low_confidence_threshold: float,
    ) -> None:
        self._simple = simple
        self._heavy = heavy
        self._heavy_fallback = heavy_fallback
        self._low_confidence_threshold = low_confidence_threshold

    async def generate(self, request: GroundedGenerationRequest) -> LLMGeneration:
        supplied_signals = request.routing
        signals = RoutingSignals(
            workload=(
                supplied_signals.workload
                if supplied_signals is not None
                else WorkloadKind.GROUNDED_ANSWER
            ),
            question=request.question,
            authorized_document_count=len({item.document_id for item in request.evidence}),
            top_retrieval_score=(
                supplied_signals.top_retrieval_score if supplied_signals is not None else None
            ),
        )
        decision = route_model(
            signals,
            low_confidence_threshold=self._low_confidence_threshold,
        )
        if decision.route is ModelRoute.HEAVY:
            return await self._generate_strong(request, decision.reason)
        try:
            generation = await self._simple.generate(request)
        except LLMProviderError as exc:
            if exc.code not in {
                LLMErrorCode.TIMEOUT,
                LLMErrorCode.TRANSIENT,
                LLMErrorCode.INVALID_RESPONSE,
                LLMErrorCode.UNAVAILABLE,
            }:
                raise LLMProviderError(
                    exc.code,
                    transient=exc.transient,
                    retry_count=exc.retry_count,
                    model_name=self._simple.model_name,
                    route_reason=decision.reason,
                ) from None
            try:
                strong = await self._heavy_fallback.generate(request)
            except LLMProviderError as strong_exc:
                raise LLMProviderError(
                    strong_exc.code,
                    transient=strong_exc.transient,
                    retry_count=1 + strong_exc.retry_count,
                    model_name=self._heavy_fallback.model_name,
                    route_reason=decision.reason,
                    fallback_used=True,
                    fallback_reason=f"SIMPLE_MODEL_{exc.code.value}",
                ) from None
            return LLMGeneration(
                answer=strong.answer,
                usage=self._usage(
                    strong.usage,
                    model_name=self._heavy_fallback.model_name,
                    reason=decision.reason,
                    fallback_used=True,
                    fallback_reason=f"SIMPLE_MODEL_{exc.code.value}",
                    extra_retries=1,
                ),
            )
        return LLMGeneration(
            answer=generation.answer,
            usage=self._usage(
                generation.usage,
                model_name=self._simple.model_name,
                reason=decision.reason,
            ),
        )

    async def _generate_strong(
        self, request: GroundedGenerationRequest, reason: RouteReason
    ) -> LLMGeneration:
        try:
            generation = await self._heavy.generate(request)
        except LLMProviderError as exc:
            raise LLMProviderError(
                exc.code,
                transient=exc.transient,
                retry_count=exc.retry_count,
                model_name=self._heavy.model_name,
                route_reason=reason,
            ) from None
        return LLMGeneration(
            answer=generation.answer,
            usage=self._usage(
                generation.usage,
                model_name=self._heavy.model_name,
                reason=reason,
            ),
        )

    @staticmethod
    def _usage(
        usage: LLMUsage,
        *,
        model_name: str,
        reason: RouteReason,
        fallback_used: bool = False,
        fallback_reason: str | None = None,
        extra_retries: int = 0,
    ) -> LLMUsage:
        return LLMUsage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            latency_ms=usage.latency_ms,
            retry_count=usage.retry_count + extra_retries,
            model_name=model_name,
            route_reason=reason.value,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
        )
