from django.template.loader import render_to_string
import tempfile
import os
import logging

logger = logging.getLogger(__name__)

try:
    from weasyprint import HTML
except OSError:
    logger.warning("WeasyPrint not available. PDF generation will fail.")
    HTML = None


def generate_analytics_pdf(data, owner_email):
    """
    Generates a professional PDF report from analytics data.
    """
    if not HTML:
        raise ImportError("WeasyPrint is not installed or configured correctly.")

    html_content = render_to_string(
        "reports/analytics_report.html",
        {
            "data": data,
            "owner_email": owner_email,
            "date": data.get("generated_at", ""),
        },
    )

    # WeasyPrint can generate PDF from HTML string
    pdf_file = HTML(string=html_content).write_pdf()
    return pdf_file
