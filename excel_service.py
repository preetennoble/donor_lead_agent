from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from io import BytesIO
from datetime import datetime

def generate_research_excel(company_data: dict) -> BytesIO:
    """
    Generate an Excel sheet containing company research data.
    Returns a BytesIO object with the Excel content.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Company Research"
    
    # Enable grid lines
    ws.views.sheetView[0].showGridLines = True
    
    # Styles
    title_font = Font(name="Calibri", size=16, bold=True, color="FFFFFF")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    bold_font = Font(name="Calibri", size=11, bold=True)
    regular_font = Font(name="Calibri", size=11)
    italic_font = Font(name="Calibri", size=11, italic=True, color="595959")
    
    title_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid") # Dark Blue
    header_fill = PatternFill(start_color="2F5597", end_color="2F5597", fill_type="solid") # Steel Blue
    zebra_fill = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid") # Soft Gray
    
    thin_border = Border(
        left=Side(style='thin', color='D9D9D9'),
        right=Side(style='thin', color='D9D9D9'),
        top=Side(style='thin', color='D9D9D9'),
        bottom=Side(style='thin', color='D9D9D9')
    )
    
    # 1. Title Row
    ws.merge_cells("A1:B1")
    title_cell = ws["A1"]
    title_cell.value = f"Company Research Report: {company_data.get('company_name', 'Unknown')}"
    title_cell.font = title_font
    title_cell.fill = title_fill
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 40
    
    # 2. Metadata Info
    ws["A2"] = "Generated On:"
    ws["A2"].font = bold_font
    ws["B2"] = datetime.now().strftime('%B %d, %Y at %I:%M %p')
    ws["B2"].font = regular_font
    ws.row_dimensions[2].height = 20
    
    # Add an empty row
    ws.row_dimensions[3].height = 15
    
    # 3. Headers
    ws["A4"] = "Field Name"
    ws["A4"].font = header_font
    ws["A4"].fill = header_fill
    ws["A4"].alignment = Alignment(horizontal="left", vertical="center")
    
    ws["B4"] = "Value / Research Data"
    ws["B4"].font = header_font
    ws["B4"].fill = header_fill
    ws["B4"].alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[4].height = 25
    
    # 4. Populate Data
    research = company_data.get('research_json', {}) or {}
    research_fields = [
        ('Industry', research.get('industry', 'Not Found')),
        ('CSR Themes', ', '.join(research.get('thematic_focus', [])) if research.get('thematic_focus') else 'Not Found'),
        ('Geography', research.get('geographical_priority', 'Not Found')),
        ('CSR Focus', research.get('company_csr_focus', 'Not Found')),
        ('Past CSR Programs', research.get('previous_education_projects', 'Not Found')),
        ('Avg Ticket Size', research.get('avg_ticket_size', 'Not Found')),
        ('Program District/State', research.get('program_district_state', 'Not Found')),
        ('Education CSR Spend', research.get('education_csr_spend', 'Not Found')),
        ('CSR Spend (Previous FY)', research.get('csr_spend_previous_fy', 'Not Found')),
        ('CSR Spend (3 FY)', research.get('csr_spend_previous_3fy', 'Not Found')),
        ('Implementation Partners', ', '.join(research.get('existing_implementation_partners', [])) if research.get('existing_implementation_partners') else 'Not Found'),
        ('Website', research.get('website', 'Not Found')),
        ('City', research.get('city', 'Not Found')),
        ('State', research.get('state', 'Not Found')),
        ('Has Company Foundation', research.get('has_company_foundation', 'Not Found')),
        ('Data Confidence', research.get('confidence', 'unverified')),
        ('Source URL', research.get('source_url', 'Not Found')),
    ]
    
    current_row = 5
    for field_name, field_value in research_fields:
        cell_a = ws.cell(row=current_row, column=1, value=field_name)
        cell_b = ws.cell(row=current_row, column=2)
        
        cell_a.font = bold_font
        cell_a.border = thin_border
        cell_b.border = thin_border
        
        # Apply zebra striping to alternating rows
        if current_row % 2 == 1:
            cell_a.fill = zebra_fill
            cell_b.fill = zebra_fill
            
        if field_value == 'Not Found' or not field_value:
            cell_b.value = "Not Found"
            cell_b.font = italic_font
        else:
            cell_b.value = str(field_value)
            cell_b.font = regular_font
            
        # Text wrapping and alignment
        cell_a.alignment = Alignment(vertical="top")
        cell_b.alignment = Alignment(vertical="top", wrap_text=True)
        
        ws.row_dimensions[current_row].height = 20
        current_row += 1
        
    # Auto-fit column widths nicely
    ws.column_dimensions['A'].width = 28
    ws.column_dimensions['B'].width = 65
    
    # Save spreadsheet to buffer
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer

def generate_research_excel_filename(company_name: str) -> str:
    """Generate a clean filename for the Excel sheet."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_name = "".join(c for c in company_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
    return f"Research_{safe_name}_{timestamp}.xlsx"
