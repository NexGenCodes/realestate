from django.template.loader import render_to_string
from weasyprint import HTML
import tempfile
import os


def generate_analytics_pdf(data, owner_email):
    """
    Generates a professional PDF report from analytics data.
    """
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
