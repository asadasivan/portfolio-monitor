from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

from app.reporting.markdown import render_markdown
from app.reporting.serialization import report_filename, write_latest_alias


def write_html_report(report: dict[str, Any], report_dir: Path) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    title = f"Portfolio {str(report.get('report_type', 'report')).title()} Report"
    markdown = escape(render_markdown(report))
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 2rem; color: #1f2933; }}
    main {{ max-width: 1100px; margin: 0 auto; }}
    pre {{ white-space: pre-wrap; background: #f6f8fa; border: 1px solid #d0d7de; padding: 1rem; overflow-x: auto; }}
  </style>
</head>
<body>
  <main>
    <pre>{markdown}</pre>
  </main>
</body>
</html>
"""
    path = report_dir / report_filename(report, "html")
    path.write_text(html, encoding="utf-8")
    write_latest_alias(path, "latest.html")
    return path
