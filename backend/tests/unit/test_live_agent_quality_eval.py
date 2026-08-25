from app.scripts.live_agent_quality_eval import _scope


def test_live_quality_scope_uses_a_valid_synthetic_identity() -> None:
    scope = _scope()

    assert scope.identity.email == "live-eval@example.com"
    assert scope.grants[0].company_slugs == ("orion-main",)
