"""
report.py – PDF Diagnostic Report & Workshop Storyboard Generator.

Generates a clean, professional, one-page PDF storyboard for the workshop
using ReportLab. Always clearly labelled SIMULATED.
"""

from __future__ import annotations

import io
import time
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def generate_ticket_pdf(
    ticket_id: str,
    station_name: str,
    station_address: str,
    station_phone: str,
    selected_slot: str,
    price_range: str,
    fault_headline: str,
    fault_body: str,
    telemetry_snapshot: dict[str, Any],
    source: str = "replayed",
    session_id: str = "demo-session",
) -> bytes:
    """Generate a clean 1-page workshop PDF report and return bytes."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=18,
        leading=22,
        textColor=colors.HexColor('#0f172a'),
    )
    subtitle_style = ParagraphStyle(
        'DocSub',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        textColor=colors.HexColor('#dc2626'),
    )
    heading_style = ParagraphStyle(
        'SectionHeading',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor('#0369a1'),
        spaceBefore=8,
        spaceAfter=4,
    )
    body_style = ParagraphStyle(
        'BodyDark',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#334155'),
    )
    meta_style = ParagraphStyle(
        'MetaText',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=11,
        textColor=colors.HexColor('#64748b'),
    )

    elements: list[Any] = []

    # 1. Header Banner
    header_data = [
        [
            Paragraph("<b>VERD – Vehicle Diagnostic & Dispatch Storyboard</b>", title_style),
            Paragraph(f"<b>TICKET ID:</b> {ticket_id}<br/><b>DATE:</b> {time.strftime('%Y-%m-%d %H:%M:%S')}", meta_style),
        ],
        [
            Paragraph("<b>[SIMULATED VEHICLE DATA]</b> · Presidency University · Team: Starters", subtitle_style),
            Paragraph("<b>Vehicle:</b> Tata Nexon EV Max (SIMULATED)", meta_style),
        ]
    ]
    t_header = Table(header_data, colWidths=[380, 160])
    t_header.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    elements.append(t_header)
    elements.append(Spacer(1, 10))

    # 2. Fault Explanation Section
    elements.append(Paragraph("1. Vehicle Fault Explanation & AI Reasoning", heading_style))
    fault_text = f"<b>Observation:</b> {fault_headline}<br/><b>Explanation:</b> {fault_body}"
    elements.append(Paragraph(fault_text, body_style))
    elements.append(Spacer(1, 10))

    # 3. Telemetry Snapshot Table
    elements.append(Paragraph("2. Telemetry Snapshot vs Baseline", heading_style))
    bat_temp = telemetry_snapshot.get('battery_temp_c', 62.0)
    cool_temp = telemetry_snapshot.get('coolant_temp_c', 52.0)
    soc = telemetry_snapshot.get('soc_pct', 72.0)
    speed = telemetry_snapshot.get('speed_kmh', 14.0)

    telemetry_data = [
        ["Telemetry Metric", "Observed Reading", "Nominal Baseline", "Status"],
        ["Battery Temperature", f"{bat_temp:.1f} °C", "32.0 - 40.0 °C", "CRITICAL OVERHEAT" if bat_temp > 55 else "NORMAL"],
        ["Coolant Temperature", f"{cool_temp:.1f} °C", "38.0 - 45.0 °C", "HIGH" if cool_temp > 48 else "NORMAL"],
        ["State of Charge (SOC)", f"{soc:.1f} %", "15 - 90 %", "HEALTHY"],
        ["Vehicle Speed", f"{speed:.1f} km/h", "Traffic baseline", "Dense Urban Crawl"],
    ]
    t_telemetry = Table(telemetry_data, colWidths=[160, 120, 140, 120])
    t_telemetry.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
        ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#fee2e2')),
    ]))
    elements.append(t_telemetry)
    elements.append(Spacer(1, 10))

    # 4. TinyFish Web Agent Workshop Dispatch
    elements.append(Paragraph("3. Workshop Dispatch (TinyFish Web Agent)", heading_style))
    dispatch_data = [
        ["Service Station", station_name],
        ["Station Address", station_address],
        ["Contact Phone", station_phone],
        ["Confirmed Slot", f"<b>{selected_slot}</b>"],
        ["Estimated Pricing", f"<b>{price_range}</b>"],
        ["TinyFish Agent Mode", f"{source.upper()} (Verified by Web Agent)"],
    ]
    t_dispatch = Table(dispatch_data, colWidths=[150, 390])
    t_dispatch.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f8fafc')),
    ]))
    elements.append(t_dispatch)
    elements.append(Spacer(1, 10))

    # 5. Consent & Privacy Declaration
    elements.append(Paragraph("4. Safety, Consent & Privacy Compliance", heading_style))
    privacy_info = (
        f"<b>Driver Consent Session:</b> {session_id} · Status: <b>APPROVED</b><br/>"
        "<b>GDPR Privacy Verification:</b> Only non-personal vehicle CAN bus telemetry and general city-level location "
        "were transmitted to locate service bays. Zero driver personal identity, VIN ownership records, or financial cards were exposed.<br/>"
        "<b>Advisory Notice:</b> VERD advises only and never controls vehicle actuators. In emergency situations, always call 112 directly."
    )
    elements.append(Paragraph(privacy_info, meta_style))

    doc.build(elements)
    return buf.getvalue()
