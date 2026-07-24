from __future__ import annotations

import re

import pytest

from mir import Signal, SignalDataType, SignalSemantic
from mir.report import render_comparison_report, render_factory_report
from mir.sim import Scenario
from mir.synth import serial_line


SCENARIO = Scenario(horizon_s=1_000, warmup_s=100, seed=23, replications=1)
FORBIDDEN_EXTERNAL_PATTERNS = (
    r"https?://",
    r"<(?:link|iframe|object|embed)\b",
    r"\b(?:src|href)\s*=",
    r"@import\b",
    r"\burl\s*\(",
    r"\bfetch\s*\(",
    r"\bxmlns\s*=",
)


def test_factory_user_text_and_diagnostic_text_are_escaped() -> None:
    factory = serial_line(stations=2, cycle_times_s=[10, 15], buffer_capacity=2)
    factory.meta.name = 'Factory </h1><script data-x="name">alert(1)</script>'
    factory.meta.description = '<img src=x onerror="alert(2)"> & description'
    factory.meta.provenance.source = 'source " onclick="alert(3)'
    factory.machines[0].name = '<svg onload="alert(4)">machine</svg>'
    factory.operations[0].name = '<b data-x="operation">Operation</b>'
    factory.operations[0].kind = 'kind <script>alert(5)</script>'
    factory.machines[0].capabilities = [factory.operations[0].kind]
    for flow in factory.flows:
        flow.material = 'part <img onerror="alert(6)"> & raw'
    factory.signals.append(
        Signal(
            id="unsafe-unit",
            tag='TAG"><script>alert(7)</script>',
            machine="machine-01",
            dtype=SignalDataType.FLOAT,
            semantic=SignalSemantic.MEASUREMENT,
            unit='</span><script>alert(8)</script>',
        )
    )

    report = render_factory_report(factory, SCENARIO)

    assert '<script data-x="name">' not in report
    assert '<img src=x onerror="alert(2)">' not in report
    assert '<svg onload="alert(4)">' not in report
    assert '<b data-x="operation">' not in report
    assert '<script>alert(5)</script>' not in report
    assert '<img onerror="alert(6)">' not in report
    assert '</span><script>alert(8)</script>' not in report
    assert '&lt;script data-x=&quot;name&quot;&gt;alert(1)&lt;/script&gt;' in report
    assert '&lt;img src=x onerror=&quot;alert(2)&quot;&gt; &amp; description' in report
    assert 'source &quot; onclick=&quot;alert(3)' in report
    assert '&lt;svg onload=&quot;alert(4)&quot;&gt;machine&lt;/svg&gt;' in report
    assert '&lt;b data-x=&quot;operation&quot;&gt;Operation&lt;/b&gt;' in report
    assert '&lt;/span&gt;&lt;script&gt;alert(8)&lt;/script&gt;' in report


def test_comparison_factory_names_are_escaped() -> None:
    baseline = serial_line(
        stations=1,
        cycle_times_s=[10],
        factory_id="baseline",
        name='<Baseline & "unsafe">',
    )
    variant = serial_line(
        stations=1,
        cycle_times_s=[8],
        factory_id="variant",
        name="Variant </h1><script>alert(1)</script>",
    )

    report = render_comparison_report(baseline, variant, SCENARIO)

    assert '<Baseline & "unsafe">' not in report
    assert "Variant </h1><script>alert(1)</script>" not in report
    assert '&lt;Baseline &amp; &quot;unsafe&quot;&gt;' in report
    assert 'Variant &lt;/h1&gt;&lt;script&gt;alert(1)&lt;/script&gt;' in report


@pytest.mark.parametrize("comparison", [False, True])
def test_report_has_only_inline_assets_and_no_generated_dom_ids(comparison: bool) -> None:
    baseline = serial_line(stations=2, cycle_times_s=[10, 15], buffer_capacity=2)
    if comparison:
        variant = serial_line(
            stations=2,
            cycle_times_s=[10, 12],
            buffer_capacity=3,
            factory_id="variant",
            name="Variant",
        )
        report = render_comparison_report(baseline, variant, SCENARIO)
    else:
        report = render_factory_report(baseline, SCENARIO)

    assert report.count("<style>") == 1
    assert report.count("<script>") == 1
    assert not re.search(r"\bid\s*=", report, flags=re.IGNORECASE)
    for pattern in FORBIDDEN_EXTERNAL_PATTERNS:
        assert not re.search(pattern, report, flags=re.IGNORECASE)
