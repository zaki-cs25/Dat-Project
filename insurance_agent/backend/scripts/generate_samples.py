"""
Generate sample Indian health insurance documents as PDFs for testing.

Usage:
    python backend/scripts/generate_samples.py

Creates 6 PDFs in the samples/ directory:
    - ir dai_policy_certificate.pdf
    - discharge_summary.pdf
    - hospital_bill.pdf
    - claim_form.pdf
    - pharmacy_bill.pdf
    - diagnostic_report.pdf
"""

import os
import sys
from datetime import datetime, timedelta
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

# Paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)  # backend/
SAMPLES_DIR = os.path.join(os.path.dirname(PROJECT_ROOT), "samples")
os.makedirs(SAMPLES_DIR, exist_ok=True)

# Colors
DARK_BLUE = HexColor("#1E3A5F")
ACCENT_BLUE = HexColor("#2B6CB0")
LIGHT_GRAY = HexColor("#F7FAFC")
BORDER_GRAY = HexColor("#E2E8F0")
TEXT_DARK = HexColor("#2D3748")
TEXT_MUTED = HexColor("#718096")

# Styles
styles = getSampleStyleSheet()

def make_style(name, parent="Normal", **kwargs):
    base = styles[parent]
    return ParagraphStyle(name, parent=base, **kwargs)

style_title = make_style("DocTitle", fontSize=18, textColor=DARK_BLUE, spaceAfter=2*mm, alignment=TA_CENTER, fontName="Helvetica-Bold")
style_subtitle = make_style("DocSubtitle", fontSize=12, textColor=ACCENT_BLUE, spaceAfter=4*mm, alignment=TA_CENTER)
style_section = make_style("Section", fontSize=11, textColor=DARK_BLUE, spaceBefore=6*mm, spaceAfter=2*mm, fontName="Helvetica-Bold")
style_label = make_style("Label", fontSize=9, textColor=TEXT_MUTED, fontName="Helvetica", leftIndent=6*mm)
style_value = make_style("Value", fontSize=9, textColor=TEXT_DARK, fontName="Helvetica-Bold", leftIndent=6*mm, spaceBefore=0, spaceAfter=1*mm)
style_body = make_style("Body", fontSize=9, textColor=TEXT_DARK, fontName="Helvetica", leftIndent=6*mm, spaceBefore=0, spaceAfter=1*mm)
style_footer = make_style("Footer", fontSize=7, textColor=TEXT_MUTED, alignment=TA_CENTER, spaceBefore=10*mm)
style_cell = make_style("Cell", fontSize=8, textColor=TEXT_DARK, fontName="Helvetica")
style_cell_header = make_style("CellHeader", fontSize=8, textColor=WHITE if 'WHITE' in dir() else "#FFFFFF", fontName="Helvetica-Bold")
style_small_right = make_style("SmallRight", fontSize=9, textColor=TEXT_DARK, alignment=TA_RIGHT, fontName="Helvetica-Bold")

WHITE = "#FFFFFF"
style_cell_header = make_style("CellHeader", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold")

def make_doc(filename):
    path = os.path.join(SAMPLES_DIR, filename)
    return SimpleDocTemplate(path, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm, topMargin=15*mm, bottomMargin=15*mm)

def hr():
    return HRFlowable(width="100%", thickness=0.5, color=BORDER_GRAY, spaceBefore=2*mm, spaceAfter=2*mm)

def spacer(mm_h=3):
    return Spacer(1, mm_h * mm)

def field_row(label, value):
    return [
        [Paragraph(f"<b>{label}</b>", style_label),
         Paragraph(str(value), style_value)],
    ]

def make_table(rows, col_widths=None):
    style_list = [
        ("BACKGROUND", (0, 0), (-1, 0), DARK_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 1), (-1, -1), LIGHT_GRAY),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER_GRAY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    table = Table(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle(style_list))
    return table


# ===================================================================
# Document 1: IRDAI Policy Certificate
# ===================================================================
def generate_policy_certificate():
    doc = make_doc("ir dai_policy_certificate.pdf")
    story = []

    story.append(Paragraph("MEDISHIELD CASHLESS HEALTH INSURANCE", style_title))
    story.append(Paragraph("POLICY CERTIFICATE", style_subtitle))
    story.append(hr())

    # Issuer info
    story.append(Paragraph("MediShield Health Solutions Pvt. Ltd.", style_body))
    story.append(Paragraph("Regd. Office: 14th Floor, Towers B & C, DLF Cyber City, Gurugram, Haryana 122002", style_body))
    story.append(Paragraph("CIN: U66000HR2012PTC059834 | Corporate IRDAI Regn No: 114", style_body))
    story.append(spacer())

    # Policy details
    story.append(Paragraph("Policy Details", style_section))
    policy_fields = [
        ("Policy Number", "MSH-2025-HP-004782"),
        ("IRDAI Registration No.", "114/HC/2024-25"),
        ("Proposal Date", "15-Jan-2025"),
        ("Policy Start Date", "01-Mar-2025"),
        ("Policy End Date", "28-Feb-2026"),
        ("Insured Person", "Rajesh Kumar Sharma"),
        ("Age / Gender", "45 / Male"),
        ("Date of Birth", "12-Aug-1979"),
        ("Address", "H.No. 245, Sector 15, Dwarka, New Delhi - 110075"),
        ("Relation to Proposer", "Self"),
    ]
    table_data = [["Field", "Details"]]
    for label, val in policy_fields:
        table_data.append([Paragraph(f"<b>{label}</b>", style_cell), Paragraph(str(val), style_cell)])
    story.append(make_table(table_data, col_widths=[70*mm, 100*mm]))
    story.append(spacer())

    # Coverage details
    story.append(Paragraph("Coverage Summary", style_section))
    coverage_fields = [
        ("Base Sum Insured", "Rs. 10,00,000/-"),
        ("Room Rent Limit", "Rs. 5,000/- per day (Single Private Room)"),
        ("Co-pay Clause", "10% co-pay on all claims (insured pays 10%, insurer pays 90%)"),
        ("Deductible", "None"),
        ("Pre-hospitalization", "30 days before admission"),
        ("Post-hospitalization", "60 days after discharge"),
        ("Day-care Procedures", "Covered as per IRDAI list of 700+ procedures"),
        ("Ambulance Charges", "Up to Rs. 1,000 per admission"),
    ]
    table_data = [["Coverage Component", "Details"]]
    for label, val in coverage_fields:
        table_data.append([Paragraph(f"<b>{label}</b>", style_cell), Paragraph(str(val), style_cell)])
    story.append(make_table(table_data, col_widths=[70*mm, 100*mm]))
    story.append(spacer())

    # Waiting periods
    story.append(Paragraph("Waiting Periods", style_section))
    story.append(Paragraph("Initial Waiting Period: 30 days from policy start date for non-PEC illnesses.", style_body))
    story.append(Paragraph("Pre-existing Diseases (PED): 48 months (4 years) from first policy inception.", style_body))
    story.append(Paragraph("Specific Diseases Waiting Period: 24 months for hernia, joint diseases, cataract, kidney stones, thyroid, sinus.", style_body))
    story.append(Paragraph("Accident: No waiting period.", style_body))
    story.append(spacer())

    # Exclusions
    story.append(Paragraph("Key Exclusions", style_section))
    exclusions = [
        "Any treatment during initial waiting period (except accidents)",
        "Pre-existing diseases within 48-month waiting period",
        "Cosmetic surgery, plastic surgery, or reconstructive surgery (unless due to accident)",
        "Dental treatment / Oral surgery (except when arising from accidental injury)",
        "Treatments under AYUSH systems (Ayurveda, Homeopathy, Unani, Siddha, Yoga)",
        "Fertility treatments including IVF, IUI, test-tube baby",
        "Treatment for HIV/AIDS and its related conditions",
        "Self-inflicted injuries or suicide attempts",
        "War, nuclear radiation, terrorism, or acts of foreign enemies",
        "Routine health check-ups, screening tests",
        "Weight loss programs, nutritional supplements",
        "Treatment at non-network hospitals for cashless (reimbursement eligible if pre-authorized)",
    ]
    for ex in exclusions:
        story.append(Paragraph(f"  {chr(8226)} {ex}", style_body))

    story.append(spacer())
    story.append(Paragraph("TPA / Network Details", style_section))
    story.append(Paragraph("Third Party Administrator: MediAssist Health Services Pvt. Ltd.", style_body))
    story.append(Paragraph("Network Hospitals: 6,500+ hospitals across India. See MediAssist app for nearest network hospital.", style_body))
    story.append(Paragraph("Cashless Eligibility: Available at all network hospitals. Pre-authorization required for planned admissions (apply 48 hrs before admission). Emergency cashless available at network hospitals with intimation within 24 hours.", style_body))

    story.append(spacer(8))
    story.append(hr())
    story.append(Paragraph("For Grievances: grievance@medishield.in | Toll-free: 1800-123-4567", style_footer))
    story.append(Paragraph("IRDAI Consumer Grievance Portal: https://igrp.irdai.gov.in | Ombudsman: health@irdai.gov.in", style_footer))

    doc.build(story)
    print(f"  Created: {os.path.join(SAMPLES_DIR, 'ir dai_policy_certificate.pdf')}")


# ===================================================================
# Document 2: Discharge Summary
# ===================================================================
def generate_discharge_summary():
    doc = make_doc("discharge_summary.pdf")
    story = []

    story.append(Paragraph("APEX SUPER SPECIALITY HOSPITAL", style_title))
    story.append(Paragraph("Multispecialty Tertiary Care Hospital", style_subtitle))
    story.append(Paragraph("Sector 62, Noida, Uttar Pradesh 201301 | Phone: 0120-456-7890", style_body))
    story.append(Paragraph("Email: records@apexhospital.com | NABL Accredited Lab", style_body))
    story.append(spacer())

    story.append(Paragraph("DISCHARGE SUMMARY", style_title))
    story.append(hr())

    # Patient details
    story.append(Paragraph("Patient Information", style_section))
    info = [
        ("Patient Name", "Rajesh Kumar Sharma"),
        ("Age / Gender", "45 Years / Male"),
        ("Bed Number", "ICU-12 (General Ward Bed G-204 from 22-May)"),
        ("Admission Number", "ADN-2025-003891"),
        ("Date of Admission", "20-May-2025, 14:30 hrs"),
        ("Date of Discharge", "26-May-2025, 11:00 hrs"),
        ("Duration of Stay", "6 days (2 days ICU, 4 days ward)"),
        ("Admitted by", "Dr. Anil Mehta, MD (General Surgery)"),
    ]
    table_data = [["Field", "Details"]]
    for label, val in info:
        table_data.append([Paragraph(f"<b>{label}</b>", style_cell), Paragraph(str(val), style_cell)])
    story.append(make_table(table_data, col_widths=[70*mm, 100*mm]))
    story.append(spacer())

    # History
    story.append(Paragraph("History of Present Illness", style_section))
    story.append(Paragraph("Patient presented to the Emergency Department with complaints of severe right upper quadrant abdominal pain since 18-May-2025, radiating to right shoulder, associated with nausea and vomiting. Fever was present with maximum recorded temperature of 101.4°F. No history of jaundice, hematemesis, or melena. Previous ultrasound (15-May-2025) showed multiple gallstones in gallbladder with signs of acute cholecystitis.", style_body))
    story.append(spacer())

    # On examination
    story.append(Paragraph("On Admission Examination", style_section))
    story.append(Paragraph("Vitals: BP 130/85 mmHg, Pulse 102/min, Temp 101.2°F, SpO2 97% on room air.", style_body))
    story.append(Paragraph("Abdomen: Distended, tenderness in right upper quadrant, positive Murphy's sign, guarding present. No organomegaly. Bowel sounds present.", style_body))
    story.append(spacer())

    # Investigations
    story.append(Paragraph("Investigations", style_section))
    inv_data = [["Test", "Result", "Reference Range"]]
    investigations = [
        ("Haemoglobin", "13.2 g/dL", "13-17 g/dL"),
        ("Total WBC Count", "14,500/cumm", "4,000-11,000/cumm"),
        ("Neutrophils", "82%", "40-75%"),
        ("Total Bilirubin", "1.8 mg/dL", "0.3-1.2 mg/dL"),
        ("Direct Bilirubin", "0.9 mg/dL", "0-0.3 mg/dL"),
        ("AST / SGOT", "78 IU/L", "0-40 IU/L"),
        ("ALT / SGPT", "95 IU/L", "0-41 IU/L"),
        ("Alkaline Phosphatase", "165 IU/L", "44-147 IU/L"),
        ("Amylase", "112 IU/L", "30-110 IU/L"),
        ("Random Blood Sugar", "186 mg/dL", "70-140 mg/dL"),
        ("Serum Creatinine", "0.9 mg/dL", "0.6-1.2 mg/dL"),
        ("USG Abdomen", "Multiple gallstones (largest 1.8 cm), GB wall thickening 5mm, pericholecystic fluid", "Normal"),
        ("CT Abdomen", "Acute calculous cholecystitis. No common bile duct dilatation.", "Normal"),
        ("ECG", "Normal sinus rhythm", "Normal"),
    ]
    for test, result, ref in investigations:
        inv_data.append([Paragraph(test, style_cell), Paragraph(result, style_cell), Paragraph(ref, style_cell)])
    story.append(make_table(inv_data, col_widths=[45*mm, 55*mm, 40*mm]))
    story.append(spacer())

    # Diagnosis
    story.append(Paragraph("Diagnosis", style_section))
    story.append(Paragraph("Admitting Diagnosis: Acute Abdomen - Rule out Acute Cholecystitis (ICD-10: R10.0, K81.0)", style_body))
    story.append(Paragraph("Final Diagnosis: Acute Calculous Cholecystitis (ICD-10: K81.0) with Gallstone Disease (ICD-10: K80.2)", style_body))
    story.append(spacer())

    # Treatment
    story.append(Paragraph("Treatment Given", style_section))
    story.append(Paragraph("Day 1-2 (ICU): IV fluids, IV antibiotics (Ceftriaxone 1g BD + Metronidazole 500mg TDS), analgesics (IV Diclofenac), antacids. NPO. Nasogastric tube. Monitoring vitals q4h.", style_body))
    story.append(Paragraph("Day 3 (22-May-2025): Laparoscopic Cholecystectomy performed under General Anaesthesia by Dr. Anil Mehta with Dr. Priya Nair (assistant). Operative findings: Gangrenous gallbladder, multiple gallstones (largest 1.8cm), dense pericholecystic adhesions. No CBD stones on Intra-operative Cholangiogram. 4 ports placed. Gallbladder excised completely. Two drains placed. Post-op period uneventful.", style_body))
    story.append(Paragraph("Day 4-6 (General Ward): Drains removed on Day 5. Oral diet started. IV antibiotics continued for 2 more days. Wound healing well. Pain controlled with oral analgesics.", style_body))
    story.append(spacer())

    # Advice
    story.append(Paragraph("Advice on Discharge", style_section))
    advice = [
        "Continue oral antibiotics (Tab. Amoxicillin-Clavulanate 625mg TDS) for 5 more days",
        "Take Tab. Pantoprazole 40mg OD for 2 weeks",
        "Avoid heavy lifting for 4 weeks",
        "Keep wound dry for 7 days, then gentle cleaning",
        "Low-fat diet for 2 weeks",
        "Follow up with Dr. Anil Mehta on 03-Jun-2025 (OPD)",
        "Report immediately if fever, wound discharge, or severe pain develops",
        "Histopathology report of gallbladder: Acute suppurative cholecystitis with gangrenous change. Margins clear.",
    ]
    for item in advice:
        story.append(Paragraph(f"  {chr(8226)} {item}", style_body))

    story.append(spacer(8))
    story.append(hr())
    story.append(Paragraph("Dr. Anil Mehta, MD (Surgery)", style_body))
    story.append(Paragraph("Regd. No: DMH-12847 | Senior Consultant - General Surgery", style_body))
    story.append(Paragraph(f"Issued on: {datetime.now().strftime('%d-%b-%Y')}", style_footer))

    doc.build(story)
    print(f"  Created: {os.path.join(SAMPLES_DIR, 'discharge_summary.pdf')}")


# ===================================================================
# Document 3: Hospital Bill
# ===================================================================
def generate_hospital_bill():
    doc = make_doc("hospital_bill.pdf")
    story = []

    story.append(Paragraph("APEX SUPER SPECIALITY HOSPITAL", style_title))
    story.append(Paragraph("ITEMIZED BILL / MASTER BILL", style_subtitle))
    story.append(Paragraph("Sector 62, Noida, UP 201301 | GSTIN: 09AABCA1234B1Z5", style_body))
    story.append(spacer())

    # Bill info
    story.append(Paragraph("Bill Details", style_section))
    info = [
        ("Bill No.", "BILL-2025-004782"),
        ("Admission No.", "ADN-2025-003891"),
        ("Patient Name", "Rajesh Kumar Sharma"),
        ("Age / Gender", "45 / Male"),
        ("Room No.", "ICU-12 / G-204"),
        ("Admission Date", "20-May-2025"),
        ("Discharge Date", "26-May-2025"),
        ("No. of Days", "6 Days (2 ICU + 4 Ward)"),
        ("Attending Doctor", "Dr. Anil Mehta"),
    ]
    table_data = [["Field", "Details"]]
    for label, val in info:
        table_data.append([Paragraph(f"<b>{label}</b>", style_cell), Paragraph(str(val), style_cell)])
    story.append(make_table(table_data, col_widths=[70*mm, 100*mm]))
    story.append(spacer())

    # Bill items
    story.append(Paragraph("Itemized Charges", style_section))
    bill_data = [["S.No.", "Description", "Qty", "Rate (Rs.)", "Amount (Rs.)"]]

    bill_items = [
        # Room rent
        ("1", "Room Rent - ICU (per day)", "2", "15,000", "30,000"),
        ("2", "Room Rent - Single Private Room (per day)", "4", "5,500", "22,000"),
        # Nursing
        ("3", "ICU Nursing Charges (per day)", "2", "3,000", "6,000"),
        ("4", "Ward Nursing Charges (per day)", "4", "800", "3,200"),
        # Doctors
        ("5", "Surgeon Fee - Laparoscopic Cholecystectomy", "1", "35,000", "35,000"),
        ("6", "Anaesthetist Fee", "1", "12,000", "12,000"),
        ("7", "ICU Consultant Fee (per day)", "2", "5,000", "10,000"),
        ("8", "Medicine Consultant Fee (per day)", "2", "2,000", "4,000"),
        ("9", "Senior Surgeon Fee (per day)", "6", "1,500", "9,000"),
        ("10", "Anaesthetist Fee (per day)", "2", "1,000", "2,000"),
        # OT
        ("11", "OT Charges - Laparoscopic Surgery", "1", "25,000", "25,000"),
        ("12", "OT Consumables (Laparoscopic ports, stapler, etc.)", "1", "18,500", "18,500"),
        ("13", "Anaesthesia Charges", "1", "8,000", "8,000"),
        # Diagnostics
        ("14", "Complete Haemogram (CBC)", "3", "350", "1,050"),
        ("15", "Liver Function Test (LFT)", "2", "650", "1,300"),
        ("16", "Kidney Function Test (KFT)", "2", "450", "900"),
        ("17", "Serum Amylase", "2", "300", "600"),
        ("18", "Random Blood Sugar", "6", "150", "900"),
        ("19", "USG Abdomen (Complete)", "1", "1,500", "1,500"),
        ("20", "CT Scan Abdomen (with contrast)", "1", "4,500", "4,500"),
        ("21", "ECG (12 Lead)", "2", "400", "800"),
        ("22", "X-Ray Chest (PA)", "1", "500", "500"),
        ("23", "Urine Routine Examination", "3", "250", "750"),
        ("24", "Intra-operative Cholangiogram", "1", "3,000", "3,000"),
        ("25", "Histopathology - Gallbladder", "1", "2,500", "2,500"),
        # Pharmacy
        ("26", "IV Ceftriaxone 1g (per dose)", "12", "85", "1,020"),
        ("27", "IV Metronidazole 500mg (per dose)", "18", "45", "810"),
        ("28", "IV Diclofenac 75mg (per dose)", "6", "120", "720"),
        ("29", "IV Pantoprazole 40mg (per dose)", "12", "95", "1,140"),
        ("30", "IV Fluids (Normal Saline / Ringer Lactate)", "10", "150", "1,500"),
        ("31", "Other IV Medications & Consumables", "1", "4,800", "4,800"),
        # Other
        ("32", "Ambulance Charges", "1", "2,500", "2,500"),
        ("33", "Oxygen Therapy (per day)", "2", "500", "1,000"),
        ("34", "Medical Consumables (dressings, syringes, etc.)", "1", "3,200", "3,200"),
    ]

    for item in bill_items:
        bill_data.append([
            Paragraph(item[0], style_cell),
            Paragraph(item[1], style_cell),
            Paragraph(item[2], style_cell),
            Paragraph(item[3], style_cell),
            Paragraph(item[4], style_cell),
        ])

    story.append(make_table(bill_data, col_widths=[10*mm, 75*mm, 12*mm, 25*mm, 28*mm]))
    story.append(spacer())

    # Totals
    story.append(Paragraph("Bill Summary", style_section))
    total_before_gst = 203440
    gst = int(total_before_gst * 0.18)
    grand_total = total_before_gst + gst

    summary_data = [["Description", "Amount (Rs.)"]]
    summary_data.append([Paragraph("Sub Total", style_cell), Paragraph(f"{total_before_gst:,}", style_cell)])
    summary_data.append([Paragraph("GST @ 18%", style_cell), Paragraph(f"{gst:,}", style_cell)])
    summary_data.append([Paragraph("<b>GRAND TOTAL</b>", style_cell_header), Paragraph(f"<b>{grand_total:,}</b>", style_cell_header)])
    summary_table = Table(summary_data, colWidths=[120*mm, 30*mm])
    summary_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER_GRAY),
        ("BACKGROUND", (0, -1), (-1, -1), LIGHT_GRAY),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(summary_table)

    story.append(spacer(8))
    story.append(hr())
    story.append(Paragraph("This is a computer-generated bill. No signature required.", style_footer))
    story.append(Paragraph(f"Generated on: {datetime.now().strftime('%d-%b-%Y %H:%M')}", style_footer))

    doc.build(story)
    print(f"  Created: {os.path.join(SAMPLES_DIR, 'hospital_bill.pdf')}")


# ===================================================================
# Document 4: Claim Form
# ===================================================================
def generate_claim_form():
    doc = make_doc("claim_form.pdf")
    story = []

    story.append(Paragraph("MEDISHIELD HEALTH SOLUTIONS", style_title))
    story.append(Paragraph("HEALTH INSURANCE CLAIM FORM (Reimbursement)", style_subtitle))
    story.append(hr())

    # Proposer details
    story.append(Paragraph("Proposer / Policyholder Details", style_section))
    props = [
        ("Name", "Rajesh Kumar Sharma"),
        ("Policy Number", "MSH-2025-HP-004782"),
        ("Address", "H.No. 245, Sector 15, Dwarka, New Delhi - 110075"),
        ("Mobile", "+91-98765-43210"),
        ("Email", "rajesh.sharma@email.com"),
    ]
    table_data = [["Field", "Details"]]
    for label, val in props:
        table_data.append([Paragraph(f"<b>{label}</b>", style_cell), Paragraph(str(val), style_cell)])
    story.append(make_table(table_data, col_widths=[70*mm, 100*mm]))
    story.append(spacer())

    # Insured person
    story.append(Paragraph("Insured Person Details", style_section))
    story.append(Paragraph("Name: Rajesh Kumar Sharma | Relation: Self | Age: 45 years", style_body))
    story.append(spacer())

    # Hospital details
    story.append(Paragraph("Hospital / Admission Details", style_section))
    hosp = [
        ("Hospital Name", "Apex Super Speciality Hospital"),
        ("Hospital Address", "Sector 62, Noida, UP 201301"),
        ("Type of Admission", "Emergency"),
        ("Date of Admission", "20-May-2025"),
        ("Date of Discharge", "26-May-2025"),
        ("Duration", "6 Days"),
        ("Attending Doctor", "Dr. Anil Mehta, MD (Surgery)"),
        ("Reason for Treatment", "Acute Abdomen, severe right upper quadrant pain"),
        ("Diagnosis", "Acute Calculous Cholecystitis (ICD-10: K81.0)"),
        ("Treatment", "Laparoscopic Cholecystectomy"),
    ]
    table_data = [["Field", "Details"]]
    for label, val in hosp:
        table_data.append([Paragraph(f"<b>{label}</b>", style_cell), Paragraph(str(val), style_cell)])
    story.append(make_table(table_data, col_widths=[70*mm, 100*mm]))
    story.append(spacer())

    # Expense breakdown
    story.append(Paragraph("Claim Expense Breakdown", style_section))
    exp_data = [["S.No.", "Expense Category", "Amount Claimed (Rs.)"]]
    expenses = [
        ("1", "Room Rent", "52,000"),
        ("2", "Nursing Charges", "9,200"),
        ("3", "Doctor / Surgeon Fees", "72,000"),
        ("4", "OT & Anaesthesia Charges", "53,500"),
        ("5", "Diagnostics / Lab Tests", "19,100"),
        ("6", "Pharmacy / Medicines", "10,990"),
        ("7", "Ambulance Charges", "2,500"),
        ("8", "Other Charges (Oxygen, consumables, etc.)", "7,200"),
    ]
    for item in expenses:
        exp_data.append([Paragraph(item[0], style_cell), Paragraph(item[1], style_cell), Paragraph(item[2], style_cell)])
    exp_data.append([Paragraph("", style_cell), Paragraph("<b>Total Claim Amount</b>", style_cell), Paragraph("<b>2,26,490</b>", style_cell)])
    story.append(make_table(exp_data, col_widths=[12*mm, 100*mm, 35*mm]))
    story.append(spacer())

    # Bank details
    story.append(Paragraph("Bank Details for Reimbursement", style_section))
    bank = [
        ("Account Holder Name", "Rajesh Kumar Sharma"),
        ("Bank Name", "State Bank of India"),
        ("Account Number", "32731485092"),
        ("IFSC Code", "SBIN0012345"),
        ("Branch", "Dwarka Sector 12, New Delhi"),
    ]
    table_data = [["Field", "Details"]]
    for label, val in bank:
        table_data.append([Paragraph(f"<b>{label}</b>", style_cell), Paragraph(str(val), style_cell)])
    story.append(make_table(table_data, col_widths=[70*mm, 100*mm]))
    story.append(spacer())

    # Documents submitted
    story.append(Paragraph("Documents Submitted with Claim", style_section))
    docs = [
        "Original hospital bill with itemized details",
        "Discharge summary from hospital",
        "All investigation reports (pre and during hospitalization)",
        "Pharmacy bills (original)",
        "Ambulance bill",
        "Cancelled cheque",
        "Copy of policy certificate",
        "FIR / accident report (if applicable) - Not applicable",
    ]
    for d in docs:
        story.append(Paragraph(f"  {chr(8226)} {d}", style_body))

    story.append(spacer())
    story.append(Paragraph("Declaration", style_section))
    story.append(Paragraph("I hereby declare that the above information is true and correct to the best of my knowledge. I authorize MediShield Health Solutions to verify the details of this claim with the hospital, doctor, and any other source as deemed necessary. I have read and understood the policy wordings and terms.", style_body))

    story.append(spacer(8))
    story.append(hr())
    story.append(Paragraph("Signature of Policyholder: ___________________     Date: 28-May-2025", style_body))

    doc.build(story)
    print(f"  Created: {os.path.join(SAMPLES_DIR, 'claim_form.pdf')}")


# ===================================================================
# Document 5: Pharmacy Bill
# ===================================================================
def generate_pharmacy_bill():
    doc = make_doc("pharmacy_bill.pdf")
    story = []

    story.append(Paragraph("MEDPLUS PHARMACY", style_title))
    story.append(Paragraph("Retail Prescription Drug Store", style_subtitle))
    story.append(Paragraph("Shop No. 12, Main Market, Sector 15, Dwarka, New Delhi - 110075", style_body))
    story.append(Paragraph("Pharmacist: Mr. Vikram Singh | Regd. No: DL-P-78432", style_body))
    story.append(Paragraph("GSTIN: 07AABFM1234C1Z8", style_body))
    story.append(spacer())

    story.append(Paragraph("PRESCRIPTION BILL", style_section))
    info = [
        ("Bill No.", "MP-2025-18934"),
        ("Date", "26-May-2025"),
        ("Patient Name", "Rajesh Kumar Sharma"),
        ("Prescribing Doctor", "Dr. Anil Mehta, Apex Super Speciality Hospital"),
    ]
    table_data = [["Field", "Details"]]
    for label, val in info:
        table_data.append([Paragraph(f"<b>{label}</b>", style_cell), Paragraph(str(val), style_cell)])
    story.append(make_table(table_data, col_widths=[70*mm, 100*mm]))
    story.append(spacer())

    # Medicine items
    story.append(Paragraph("Medicines Dispensed (Post-Hospitalization)", style_section))
    med_data = [["S.No.", "Medicine Name", "Generic Name", "Qty", "MRP (Rs.)", "Amount (Rs.)"]]
    medicines = [
        ("1", "Augmentin 625mg (10 tabs)", "Amoxicillin + Clavulanic Acid", "3 strips", "185", "555"),
        ("2", "Pan-D 40 (15 caps)", "Pantoprazole + Domperidone", "2 strips", "210", "420"),
        ("3", "Himalaya Liv.52 DS (20 tabs)", "Herbal Hepatoprotective", "2 strips", "165", "330"),
        ("4", "Shelcal 500 (15 tabs)", "Calcium + Vitamin D3", "2 strips", "110", "220"),
        ("5", "Napa-P 50mg (10 tabs)", "Naproxen + Pantoprazole", "2 strips", "175", "350"),
        ("6", "Augmentin 625mg (10 tabs)", "Amoxicillin + Clavulanic Acid", "1 strip", "185", "185"),
    ]
    for med in medicines:
        med_data.append([Paragraph(med[0], style_cell), Paragraph(med[1], style_cell), Paragraph(med[2], style_cell), Paragraph(med[3], style_cell), Paragraph(med[4], style_cell), Paragraph(med[5], style_cell)])
    story.append(make_table(med_data, col_widths=[10*mm, 40*mm, 35*mm, 10*mm, 18*mm, 18*mm]))
    story.append(spacer())

    story.append(Paragraph("<b>Total Amount: Rs. 2,060/-</b> (GST included)", style_body))
    story.append(Paragraph("Payment Mode: UPI", style_body))

    story.append(spacer(8))
    story.append(hr())
    story.append(Paragraph("Thank you for your purchase. Please consult your doctor before self-medication.", style_footer))

    doc.build(story)
    print(f"  Created: {os.path.join(SAMPLES_DIR, 'pharmacy_bill.pdf')}")


# ===================================================================
# Document 6: Diagnostic Lab Report
# ===================================================================
def generate_diagnostic_report():
    doc = make_doc("diagnostic_report.pdf")
    story = []

    story.append(Paragraph("CARE DIAGNOSTICS", style_title))
    story.append(Paragraph("Pathology & Imaging Centre", style_subtitle))
    story.append(Paragraph("NABL Accredited (ISO 15189) | IAC Licensed", style_body))
    story.append(Paragraph("56-A, Guru Tegh Bahadur Avenue, Dwarka, New Delhi - 110075", style_body))
    story.append(spacer())

    story.append(Paragraph("LABORATORY INVESTIGATION REPORT", style_section))
    info = [
        ("Report No.", "CD-2025-84721"),
        ("Date of Report", "15-May-2025"),
        ("Patient Name", "Rajesh Kumar Sharma"),
        ("Age / Gender", "45 / Male"),
        ("Referring Doctor", "Dr. Kavita Singh (GP, Dwarka)"),
        ("Date of Collection", "15-May-2025, 08:30 AM"),
    ]
    table_data = [["Field", "Details"]]
    for label, val in info:
        table_data.append([Paragraph(f"<b>{label}</b>", style_cell), Paragraph(str(val), style_cell)])
    story.append(make_table(table_data, col_widths=[70*mm, 100*mm]))
    story.append(spacer())

    story.append(Paragraph("Clinical History: Right upper quadrant abdominal pain x 5 days. Radiating to right shoulder. Associated nausea. Suspected gall bladder pathology.", style_body))
    story.append(spacer())

    # Blood tests
    story.append(Paragraph("Haematology", style_section))
    h_data = [["Test", "Result", "Units", "Reference Range", "Flag"]]
    haem = [
        ("Haemoglobin", "13.2", "g/dL", "13.0-17.0", ""),
        ("Total WBC Count", "13,800", "/cumm", "4,000-11,000", "H"),
        ("Neutrophils", "79%", "%", "40-75", "H"),
        ("Lymphocytes", "16%", "%", "20-40", "L"),
        ("Eosinophils", "2%", "%", "1-6", ""),
        ("Platelet Count", "2.1 Lakhs", "/cumm", "1.5-4.5 Lakhs", ""),
        ("ESR (1st hour)", "38", "mm/hr", "0-20", "H"),
    ]
    for row in haem:
        flag = f" <font color='#E53E3E'><b>{row[4]}</b></font>" if row[4] else ""
        h_data.append([
            Paragraph(row[0], style_cell),
            Paragraph(row[1], style_cell),
            Paragraph(row[2], style_cell),
            Paragraph(row[3], style_cell),
            Paragraph(flag, style_cell),
        ])
    story.append(make_table(h_data, col_widths=[35*mm, 20*mm, 15*mm, 30*mm, 15*mm]))
    story.append(spacer())

    story.append(Paragraph("Liver Function Tests", style_section))
    l_data = [["Test", "Result", "Units", "Reference Range", "Flag"]]
    liver = [
        ("Total Bilirubin", "1.8", "mg/dL", "0.3-1.2", "H"),
        ("Direct Bilirubin", "0.9", "mg/dL", "0-0.3", "H"),
        ("Indirect Bilirubin", "0.9", "mg/dL", "0.1-0.9", ""),
        ("AST (SGOT)", "78", "IU/L", "0-40", "H"),
        ("ALT (SGPT)", "95", "IU/L", "0-41", "H"),
        ("Alkaline Phosphatase", "165", "IU/L", "44-147", "H"),
        ("Total Protein", "6.8", "g/dL", "6.0-8.3", ""),
        ("Albumin", "4.2", "g/dL", "3.5-5.5", ""),
    ]
    for row in liver:
        flag = f" <font color='#E53E3E'><b>{row[4]}</b></font>" if row[4] else ""
        l_data.append([
            Paragraph(row[0], style_cell),
            Paragraph(row[1], style_cell),
            Paragraph(row[2], style_cell),
            Paragraph(row[3], style_cell),
            Paragraph(flag, style_cell),
        ])
    story.append(make_table(l_data, col_widths=[35*mm, 20*mm, 15*mm, 30*mm, 15*mm]))
    story.append(spacer())

    story.append(Paragraph("Serum Amylase", style_section))
    story.append(Paragraph("Result: 112 IU/L (Reference: 30-110 IU/L) - Mildly Elevated", style_body))
    story.append(spacer())

    story.append(Paragraph("Ultrasound Abdomen (Complete)", style_section))
    usg_findings = [
        "Liver: Normal size and echotexture. No focal lesion seen.",
        "Gallbladder: Multiple gallstones noted, largest measuring 1.8 cm in anteroposterior dimension. Gallbladder wall is thickened measuring 5 mm. Pericholecystic fluid collection noted. Sonographic Murphy's sign is positive.",
        "Common Bile Duct: Not dilated. Measures 3 mm in diameter.",
        "Pancreas: Normal size, shape, and echotexture. No mass or duct dilatation.",
        "Spleen: Normal size (10.2 cm). Normal echotexture.",
        "Kidneys: Both kidneys normal in size and echotexture. No calculi or hydronephrosis.",
        "Aorta & IVC: Normal calibre. No aneurysm.",
        "Free Fluid: Minimal free fluid noted in Morison's pouch.",
    ]
    for f in usg_findings:
        story.append(Paragraph(f"  {chr(8226)} {f}", style_body))

    story.append(spacer())
    story.append(Paragraph("IMPRESSION", style_section))
    story.append(Paragraph("USG findings are consistent with Acute Calculous Cholecystitis with gallstone disease. CBD not dilated -- no evidence of choledocholithiasis on USG. Recommend surgical opinion.", style_body))

    story.append(spacer(8))
    story.append(hr())
    story.append(Paragraph("Dr. Meera Iyer, MD (Pathology)", style_body))
    story.append(Paragraph("Radiologist: Dr. Sameer Khan, MD (Radiology)", style_body))
    story.append(Paragraph(f"Report Generated: {datetime.now().strftime('%d-%b-%Y')}", style_footer))

    doc.build(story)
    print(f"  Created: {os.path.join(SAMPLES_DIR, 'diagnostic_report.pdf')}")


# ===================================================================
# Main
# ===================================================================
if __name__ == "__main__":
    print("Generating sample PDF documents in samples/ directory...")
    generate_policy_certificate()
    generate_discharge_summary()
    generate_hospital_bill()
    generate_claim_form()
    generate_pharmacy_bill()
    generate_diagnostic_report()
    print("Done!")
