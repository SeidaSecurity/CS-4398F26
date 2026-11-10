import pytest

from app.config_templates import TemplateRenderError, render_template, template_variables


def test_template_variables_are_unique_and_sorted():
    assert template_variables("{{ vlan }} {{interface}} {{ vlan }}") == ["interface", "vlan"]


def test_render_template_substitutes_values_without_evaluating_them():
    assert render_template(
        "description {{ label }}",
        {"label": "Office {{ untouched }}"},
    ) == "description Office {{ untouched }}"


@pytest.mark.parametrize(
    ("configuration", "variables", "message"),
    [
        ("hostname {{ hostname }}", {}, "Missing template values: hostname"),
        (
            "hostname {{ hostname }}",
            {"hostname": "edge", "unused": "x"},
            "Unused template values: unused",
        ),
        ("hostname {{ host-name }}", {}, "Use {{ variable_name }} placeholders"),
    ],
)
def test_invalid_templates_are_rejected(configuration, variables, message):
    with pytest.raises(TemplateRenderError, match=message):
        render_template(configuration, variables)
