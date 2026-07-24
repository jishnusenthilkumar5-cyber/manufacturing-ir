from __future__ import annotations

from mir.passes.base import PassContext, PassManager, PassResult
from tests.test_validation import clean_factory


class FirstPass:
    name = "first"
    requires: tuple[str, ...] = ()

    def run(self, factory, context: PassContext) -> PassResult:
        return PassResult(artifacts={"value": 41})


class SecondPass:
    name = "second"
    requires = ("first",)

    def run(self, factory, context: PassContext) -> PassResult:
        return PassResult(artifacts={"value": context.require("first", "value") + 1})


def test_dependencies_are_resolved_and_artifacts_are_shared() -> None:
    manager = PassManager([SecondPass(), FirstPass()])
    result = manager.run(clean_factory(), targets=["second"])
    assert result.executed == ("first", "second")
    assert result.artifacts["second"]["value"] == 42
