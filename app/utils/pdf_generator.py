# app/utils/pdf_generator.py

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from fastapi.responses import StreamingResponse
import io


def generar_pdf(template_name: str, model: dict, filename: str) -> StreamingResponse:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = []

    # Título
    title_style = ParagraphStyle('title', parent=styles['Heading1'],
    textColor=colors.HexColor('#004d00'), fontSize=18)
    elements.append(Paragraph("ENVIEXPRESS", title_style))

    subtitle = "Reporte de Envíos" if "envios" in template_name else "Reporte de Usuarios"
    elements.append(Paragraph(subtitle, styles['Heading2']))
    elements.append(Spacer(1, 0.2 * inch))

    # Info del reporte
    elements.append(Paragraph(f"<b>Fecha:</b> {model.get('fecha', '')}", styles['Normal']))
    if model.get('desde'):
        elements.append(Paragraph(f"<b>Desde:</b> {model.get('desde')}", styles['Normal']))
    if model.get('hasta'):
        elements.append(Paragraph(f"<b>Hasta:</b> {model.get('hasta')}", styles['Normal']))
    elements.append(Paragraph(f"<b>Total:</b> {model.get('total', 0)}", styles['Normal']))
    elements.append(Spacer(1, 0.3 * inch))

    # Tabla de envíos
    if "envios" in template_name:
        headers = ["Nº Guía", "Cliente", "Origen", "Destino", "Peso", "Costo", "Estado", "Fecha"]
        data = [headers]
        for e in model.get("envios", []):
            data.append([
                e.get("numero_guia", ""),
                e.get("cliente_nombre", ""),
                e.get("origen_ciudad", ""),
                e.get("destino_ciudad", ""),
                f"{e.get('peso', '')} kg",
                f"${e.get('costo_envio', '')}",
                e.get("estado", ""),
                e.get("fecha_creacion", "")
            ])
        if model.get("total_costos"):
            elements.append(Paragraph(f"<b>Total costos:</b> ${model.get('total_costos')}", styles['Normal']))

    # Tabla de usuarios
    else:
        headers = ["ID", "Usuario", "Nombre", "Correo", "Teléfono", "Rol", "Activo"]
        data = [headers]
        for u in model.get("usuarios", []):
            data.append([
                str(u.id_usuario),
                u.user_name,
                f"{u.nombre} {u.apellido}",
                u.correo,
                u.telefono or "-",
                u.rol,
                "Sí" if u.activo else "No"
            ])

    # Estilo de tabla
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#004d00')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9f9f9')]),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))

    elements.append(table)
    elements.append(Spacer(1, 0.3 * inch))
    elements.append(Paragraph("Sistema de Gestión de Envíos - EnviExpress © 2025", styles['Normal']))

    doc.build(elements)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}.pdf"}
    )