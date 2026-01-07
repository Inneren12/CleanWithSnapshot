import json
from pathlib import Path

TOKEN_MAP = {
    "colors": "color",
    "radii": "radius",
    "spacing": "space",
    "typography": "type",
    "shadows": "shadow",
    "borders": "border",
}


def _normalize_key(key: str) -> str:
    return key.replace("_", "-")


def _flatten_tokens(prefix: str, value, output: list[tuple[str, str]]) -> None:
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            next_key = f"{prefix}-{_normalize_key(child_key)}" if prefix else _normalize_key(child_key)
            _flatten_tokens(next_key, child_value, output)
    else:
        output.append((prefix, str(value)))


def build_tokens(tokens_path: Path) -> str:
    data = json.loads(tokens_path.read_text(encoding="utf-8"))
    variables: list[tuple[str, str]] = []

    for section_key, section_value in data.items():
        prefix = TOKEN_MAP.get(section_key, section_key)
        _flatten_tokens(prefix, section_value, variables)

    lines = ["/* Generated from design/tokens.json. Do not edit directly. */", ":root {"]
    for name, value in variables:
        lines.append(f"  --{name}: {value};")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def write_tokens(tokens_css: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(tokens_css, encoding="utf-8")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    tokens_path = root / "design" / "tokens.json"
    tokens_css = build_tokens(tokens_path)

    outputs = [
        root / "web" / "app" / "styles" / "tokens.css",
    ]

    for output in outputs:
        write_tokens(tokens_css, output)


if __name__ == "__main__":
    main()
