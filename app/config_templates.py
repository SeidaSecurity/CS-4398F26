import re

PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


class TemplateRenderError(ValueError):
    pass


def template_variables(configuration: str) -> list[str]:
    remainder = PLACEHOLDER.sub("", configuration)
    if "{{" in remainder or "}}" in remainder:
        raise TemplateRenderError(
            "Use {{ variable_name }} placeholders with letters, numbers, and underscores"
        )
    return sorted(set(PLACEHOLDER.findall(configuration)))


def render_template(configuration: str, variables: dict[str, str]) -> str:
    required = set(template_variables(configuration))
    supplied = set(variables)
    missing = sorted(required - supplied)
    extra = sorted(supplied - required)
    if missing:
        raise TemplateRenderError(f"Missing template values: {', '.join(missing)}")
    if extra:
        raise TemplateRenderError(f"Unused template values: {', '.join(extra)}")
    return PLACEHOLDER.sub(lambda match: variables[match.group(1)], configuration)
