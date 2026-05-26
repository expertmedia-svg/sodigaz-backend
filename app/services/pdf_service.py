import io
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
from reportlab.pdfgen import canvas
from app.models import Program, ProgramLine

class NumberedCanvas(canvas.Canvas):
    """Canvas personnalisé pour ajouter les numéros de page et un en-tête/pied de page élégant."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        
        # En-tête (sauf sur la première page si désiré, mais ici sur toutes les pages pour uniformité)
        self.setFont("Helvetica-Bold", 8)
        self.setFillColor(colors.HexColor("#1A365D")) # Bleu marine Sodigaz
        self.drawString(30, 815, "SODIGAZ - SYSTEME DE GESTION LOGISTIQUE")
        
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#718096"))
        self.drawRightString(565, 815, f"Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}")
        
        # Ligne de séparation en-tête
        self.setStrokeColor(colors.HexColor("#E2E8F0"))
        self.setLineWidth(0.5)
        self.line(30, 808, 565, 808)
        
        # Pied de page
        self.line(30, 45, 565, 45)
        self.drawString(30, 32, "Document officiel Sodigaz - Validé électroniquement")
        self.drawRightString(565, 32, f"Page {self._pageNumber} sur {page_count}")
        
        self.restoreState()


def generate_program_pdf_stream(program: Program) -> io.BytesIO:
    """Génère un flux PDF professionnel pour un programme logistique validé."""
    buffer = io.BytesIO()
    
    # Configuration du document A4 avec marges
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=30,
        rightMargin=30,
        topMargin=50,
        bottomMargin=60
    )
    
    # Styles
    styles = getSampleStyleSheet()
    
    # Définition de styles personnalisés
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#1A365D")
    )
    
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=12,
        textColor=colors.HexColor("#4A5568")
    )
    
    h2_style = ParagraphStyle(
        'Heading2',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#2C5282")
    )
    
    cell_bold_style = ParagraphStyle(
        'CellBold',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#2D3748")
    )
    
    cell_style = ParagraphStyle(
        'CellRegular',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#2D3748")
    )
    
    header_style = ParagraphStyle(
        'HeaderRegular',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        textColor=colors.white
    )

    story = []
    
    # 1. En-tête principal de la fiche
    prog_type_fr = "DE LIVRAISON" if program.program_type.value == "DELIVERY" else "DE COLLECTE"
    story.append(Paragraph(f"FICHE DE PROGRAMME {prog_type_fr}", title_style))
    story.append(Paragraph(f"Code unique du programme : <b>{program.program_code}</b>", subtitle_style))
    story.append(Spacer(1, 15))
    
    # 2. Métadonnées opérationnelles (grille 2 colonnes sous forme de Table)
    driver_name = program.driver.full_name or program.driver.username if program.driver else "Non assigné"
    driver_phone = program.driver.phone if program.driver and program.driver.phone else "-"
    truck_info = f"{program.truck.license_plate} ({program.truck.model or 'Camion'})" if program.truck else "Aucun"
    depot_name = program.depot.name if program.depot else "-"
    
    meta_data = [
        [
            Paragraph("<b>Informations Générales</b>", cell_bold_style),
            Paragraph("<b>Acteurs & Équipements</b>", cell_bold_style)
        ],
        [
            Paragraph(f"<b>Type :</b> {program.program_type.value} ({prog_type_fr.lower()})", cell_style),
            Paragraph(f"<b>Chauffeur :</b> {driver_name}", cell_style)
        ],
        [
            Paragraph(f"<b>Date planifiée :</b> {program.program_date.strftime('%d/%m/%Y')}", cell_style),
            Paragraph(f"<b>Téléphone Chauffeur :</b> {driver_phone}", cell_style)
        ],
        [
            Paragraph(f"<b>Statut global :</b> {program.status.upper()}", cell_style),
            Paragraph(f"<b>Camion / Plaque :</b> {truck_info}", cell_style)
        ],
        [
            Paragraph(f"<b>Système source :</b> {program.source_system.upper()}", cell_style),
            Paragraph(f"<b>Dépôt de départ :</b> {depot_name}", cell_style)
        ]
    ]
    
    meta_table = Table(meta_data, colWidths=[267, 268])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (1, 0), colors.HexColor("#EDF2F7")),
        ('PADDING', (0, 0), (-1, -1), 6),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor("#CBD5E0")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    
    story.append(meta_table)
    story.append(Spacer(1, 20))
    
    # 3. Liste des lignes du programme (Articles & Quantités)
    story.append(Paragraph("Détail des lignes et quantités validées", h2_style))
    story.append(Spacer(1, 6))
    
    # Construction du tableau des lignes
    lines_headers = [
        Paragraph("Client (Code & Nom)", header_style),
        Paragraph("Article", header_style),
        Paragraph("Planifié", header_style),
        Paragraph("Réalisé", header_style),
        Paragraph("Prix Unitaire", header_style),
        Paragraph("Montant Total", header_style)
    ]
    
    table_data = [lines_headers]
    
    total_planned = 0
    total_confirmed = 0
    total_valeur = 0
    
    for line in program.lines:
        qty_real = line.quantity_collected if program.program_type.value == "COLLECTION" else line.quantity_delivered
        total_planned += line.quantity_planned
        total_confirmed += qty_real
        
        price_val = line.unit_price or 0
        total_line_amount = (qty_real * price_val) if qty_real else 0
        total_valeur += total_line_amount
        
        client_lbl = f"({line.client_code}) {line.client_name}" if line.client_code else line.client_name
        prod_lbl = line.product_label or line.product_code
        
        price_str = f"{int(price_val):,} FCFA" if price_val else "0 FCFA"
        total_line_str = f"{int(total_line_amount):,} FCFA" if total_line_amount else "- FCFA"
        
        table_data.append([
            Paragraph(client_lbl, cell_style),
            Paragraph(prod_lbl, cell_style),
            Paragraph(str(line.quantity_planned), cell_style),
            Paragraph(str(qty_real), cell_style),
            Paragraph(price_str, cell_style),
            Paragraph(total_line_str, cell_style)
        ])
        
    # Ligne des totaux
    table_data.append([
        Paragraph("<b>TOTAL DU PROGRAMME</b>", cell_bold_style),
        Paragraph("", cell_style),
        Paragraph(f"<b>{total_planned}</b>", cell_bold_style),
        Paragraph(f"<b>{total_confirmed}</b>", cell_bold_style),
        Paragraph("", cell_style),
        Paragraph(f"<b>{total_valeur:,} FCFA</b>", cell_bold_style)
    ])
    
    # 535 points de largeur disponible au total
    lines_table = Table(table_data, colWidths=[180, 95, 50, 50, 80, 80])
    lines_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1A365D")),
        ('ALIGN', (2, 0), (-1, -1), 'CENTER'),
        ('PADDING', (0, 0), (-1, -1), 6),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor("#CBD5E0")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor("#F7FAFC")]),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor("#EDF2F7")),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E0")),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    
    story.append(lines_table)
    story.append(Spacer(1, 30))
    
    # 4. Signatures de validation
    sig_data = [
        [
            Paragraph("<b>Signature Chauffeur (Ravitailleur)</b>", cell_bold_style),
            Paragraph("<b>Signature Superviseur Logistique</b>", cell_bold_style)
        ],
        [
            Paragraph("<br/><br/><br/>____________________________________", cell_style),
            Paragraph("<br/><br/><br/>____________________________________", cell_style)
        ],
        [
            Paragraph(f"Nom : {driver_name}", cell_style),
            Paragraph("Nom : SODIGAZ Administrateur", cell_style)
        ]
    ]
    
    sig_table = Table(sig_data, colWidths=[267, 268])
    sig_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('PADDING', (0, 0), (-1, -1), 8),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    
    story.append(KeepTogether([
        Paragraph("Signatures de fin de tournée", h2_style),
        Spacer(1, 6),
        sig_table
    ]))
    
    # Génération effective du PDF
    doc.build(story, canvasmaker=NumberedCanvas)
    
    buffer.seek(0)
    return buffer
