from datetime import datetime

from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas


def export_receipt(store, identifier, path):
    sale, lines = store.receipt(identifier)
    pdf = canvas.Canvas(str(path), pagesize=(420, 595))
    pdf.setTitle("StockDesk / " + identifier[:8])

    def header():
        pdf.setFillColorRGB(0.13, 0.21, 0.26)
        pdf.rect(0, 510, 420, 85, fill=1, stroke=0)
        pdf.setFillColorRGB(1, 1, 1)
        pdf.setFont("Helvetica-Bold", 22)
        pdf.drawString(28, 552, "STOCKDESK")
        pdf.setFont("Helvetica", 10)
        pdf.drawString(28, 530, "REGISTRO INTERNO / NO ES UN COMPROBANTE FISCAL")
        pdf.setFillColorRGB(0.1, 0.1, 0.1)

    header()
    pdf.setFont("Helvetica", 10)
    pdf.drawString(28, 486, "Venta: " + identifier[:12])
    pdf.drawString(28, 470, datetime.fromtimestamp(sale["created"]).strftime("%Y-%m-%d %H:%M"))
    pdf.drawString(28, 454, "Estado: " + ("ANULADA" if sale["cancelled"] else "REGISTRADA"))
    y = 432
    for text in simpleSplit("Cliente: " + (sale["customer"] or "Sin nombre"), "Helvetica", 10, 360):
        pdf.drawString(28, y, text)
        y -= 14
    y -= 18
    for line in lines:
        if y < 90:
            pdf.showPage()
            header()
            pdf.setFont("Helvetica", 10)
            y = 480
        for text in simpleSplit(line["sku"] + " / " + line["name"], "Helvetica", 10, 360):
            if y < 70:
                pdf.showPage()
                header()
                pdf.setFont("Helvetica", 10)
                y = 480
            pdf.drawString(28, y, text)
            y -= 14
        pdf.drawString(28, y, f"{line['quantity']} x {line['price'] / 100:.2f}")
        pdf.drawRightString(
            390, y, f"{line['quantity'] * line['price'] / 100:.2f} {sale['currency']}"
        )
        y -= 28
    if y < 80:
        pdf.showPage()
        header()
        y = 470
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(28, y - 20, "TOTAL")
    pdf.drawRightString(390, y - 20, f"{sale['total'] / 100:.2f} {sale['currency']}")
    pdf.save()
