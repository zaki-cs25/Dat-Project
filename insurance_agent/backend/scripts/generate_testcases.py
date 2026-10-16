"""
Generate 4 additional test cases for health claims adjudication.

Each test case uses the SAME policy certificate but different claim documents
designed to trigger a specific verdict:

  test2 → APPROVE  (accident, all within limits)
  test3 → REJECT   (pre-existing disease, within waiting period)
  test4 → PARTIAL  (high room rent + sub-limit exceeded)
  test5 → ESCALATE (conflicting dates between bill and discharge summary)

Usage:
    python3 backend/scripts/generate_testcases.py
"""

import os
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

# Paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
SAMPLES_DIR = os.path.join(os.path.dirname(PROJECT_ROOT), "samples")

# Colors
DARK_BLUE = HexColor("#1E3A5F")
ACCENT_BLUE = HexColor("#2B6CB0")
LIGHT_GRAY = HexColor("#F7FAFC")
BORDER_GRAY = HexColor("#E2E8F0")
TEXT_DARK = HexColor("#2D3748")
TEXT_MUTED = HexColor("#718096")
WHITE = "#FFFFFF"

# Styles
styles = getSampleStyleSheet()

def make_style(name, parent="Normal", **kwargs):
    base = styles[parent]
    return ParagraphStyle(name, parent=base, **kwargs)

style_title = make_style("T", fontSize=16, textColor=DARK_BLUE, spaceAfter=2*mm, alignment=TA_CENTER, fontName="Helvetica-Bold")
style_subtitle = make_style("ST", fontSize=10, textColor=ACCENT_BLUE, spaceAfter=4*mm, alignment=TA_CENTER)
style_section = make_style("S", fontSize=10, textColor=DARK_BLUE, spaceBefore=5*mm, spaceAfter=1*mm, fontName="Helvetica-Bold")
style_body = make_style("B", fontSize=8.5, textColor=TEXT_DARK, fontName="Helvetica", leftIndent=4*mm, spaceBefore=0, spaceAfter=0.8*mm)
style_cell = make_style("C", fontSize=8, textColor=TEXT_DARK, fontName="Helvetica")
style_cellbold = make_style("CB", fontSize=8, textColor=TEXT_DARK, fontName="Helvetica-Bold")
style_footer = make_style("F", fontSize=7, textColor=TEXT_MUTED, alignment=TA_CENTER, spaceBefore=8*mm)

def make_doc(filename, subdir=None):
    d = SAMPLES_DIR
    if subdir:
        d = os.path.join(SAMPLES_DIR, subdir)
        os.makedirs(d, exist_ok=True)
    path = os.path.join(d, filename)
    return SimpleDocTemplate(path, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm, topMargin=15*mm, bottomMargin=15*mm)

def hr():
    return HRFlowable(width="100%", thickness=0.5, color=BORDER_GRAY, spaceBefore=2*mm, spaceAfter=2*mm)

def sp(mm_h=2):
    return Spacer(1, mm_h * mm)

def info_table(fields):
    data = [["Field", "Details"]]
    for label, val in fields:
        data.append([Paragraph(f"<b>{label}</b>", style_cell), Paragraph(str(val), style_cell)])
    t = Table(data, colWidths=[70*mm, 100*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER_GRAY),
        ("BACKGROUND", (0, 1), (-1, -1), LIGHT_GRAY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


# ===================================================================
# Test Case 2: APPROVE — Accident, all within limits
# ===================================================================
def generate_test2():
    sub = "test2_approve"
    print(f"\n--- Test Case 2: APPROVE (accident, all within limits) ---")

    # Discharge Summary
    doc = make_doc("discharge_summary.pdf", sub)
    story = []
    story.append(Paragraph("CAREWELL MULTISPECIALTY HOSPITAL", style_title))
    story.append(Paragraph("DISCHARGE SUMMARY", style_subtitle))
    story.append(hr())
    story.append(Paragraph("Patient Information", style_section))
    story.append(info_table([
        ("Patient Name", "Rajesh Kumar Sharma"),
        ("Age / Gender", "45 Years / Male"),
        ("Bed Number", "Ward B-105"),
        ("Admission Number", "CW-2025-011847"),
        ("Date of Admission", "10-Jun-2025, 09:15 hrs (Emergency)"),
        ("Date of Discharge", "14-Jun-2025, 10:00 hrs"),
        ("Duration of Stay", "4 days"),
        ("Attending Doctor", "Dr. Neha Kapoor, MS (Orthopedics)"),
    ]))
    story.append(sp())
    story.append(Paragraph("History of Present Illness", style_section))
    story.append(Paragraph("Patient brought to Emergency Department following road traffic accident on 10-Jun-2025. Struck by a two-wheeler while crossing at a signal. Complains of severe pain in left lower limb, visible deformity at mid-shaft tibia region. No loss of consciousness. No head injury. No internal bleeding noted.", style_body))
    story.append(sp())
    story.append(Paragraph("Investigations", style_section))
    story.append(Paragraph("Haemoglobin: 12.8 g/dL | WBC: 11,200/cumm | Random Blood Sugar: 110 mg/dL | Serum Creatinine: 0.8 mg/dL | INR: 1.0", style_body))
    story.append(Paragraph("X-Ray Left Tibia-Fibula: Closed fracture of mid-shaft left tibia, comminuted fracture of left fibula. No displacement of fragments.", style_body))
    story.append(Paragraph("CT Scan: No intra-articular involvement. Distal fragments aligned.", style_body))
    story.append(sp())
    story.append(Paragraph("Diagnosis", style_section))
    story.append(Paragraph("Final Diagnosis: Closed Fracture of Left Tibia and Fibula (ICD-10: S82.201A)", style_body))
    story.append(sp())
    story.append(Paragraph("Treatment Given", style_section))
    story.append(Paragraph("Day 1: Immobilization, IV analgesics (Tramadol), tetanus toxoid, wound cleaning. X-ray confirmed fracture.", style_body))
    story.append(Paragraph("Day 2 (12-Jun-2025): Closed reduction and intramedullary nailing of left tibia performed under spinal anaesthesia by Dr. Neha Kapoor. Intra-operative fluoroscopy showed good alignment. Plaster slab applied.", style_body))
    story.append(Paragraph("Day 3-4: Oral analgesics, anti-coagulants (Enoxaparin), wound dressing. Mobilization with crutches. Discharged in stable condition.", style_body))
    story.append(sp())
    story.append(Paragraph("Advice on Discharge", style_section))
    advice = [
        "Continue Tab. Tab-Dolo 650mg SOS for pain",
        "Tab. Ecosprin 150mg OD for 4 weeks",
        "Strict non-weight bearing for 6 weeks",
        "Follow up on 22-Jun-2025 with X-ray",
        "Physiotherapy to start after 2 weeks (ankle pumps)",
        "Wound review in 10 days",
    ]
    for a in advice:
        story.append(Paragraph(f"  {chr(8226)} {a}", style_body))
    story.append(sp(6))
    story.append(Paragraph("Dr. Neha Kapoor, MS (Orthopedics)", style_body))
    story.append(Paragraph("Regd. No: DL-MS-45892 | Consultant Orthopedic Surgeon", style_footer))
    doc.build(story)
    print(f"  Created: {os.path.join(SAMPLES_DIR, sub, 'discharge_summary.pdf')}")

    # Hospital Bill
    doc = make_doc("hospital_bill.pdf", sub)
    story = []
    story.append(Paragraph("CAREWELL MULTISPECIALTY HOSPITAL", style_title))
    story.append(Paragraph("ITEMIZED BILL", style_subtitle))
    story.append(hr())
    story.append(info_table([
        ("Bill No.", "CW-BILL-2025-008834"),
        ("Patient Name", "Rajesh Kumar Sharma"),
        ("Admission No.", "CW-2025-011847"),
        ("Admission Date", "10-Jun-2025"),
        ("Discharge Date", "14-Jun-2025"),
        ("Duration", "4 Days"),
    ]))
    story.append(sp())
    story.append(Paragraph("Itemized Charges", style_section))
    bill_data = [["S.No.", "Description", "Qty", "Rate (Rs.)", "Amount (Rs.)"]]
    items = [
        ("1", "Room Rent - Semi-Private (per day)", "4", "3,500", "14,000"),
        ("2", "Nursing Charges (per day)", "4", "500", "2,000"),
        ("3", "Surgeon Fee - IM Nailing Tibia", "1", "25,000", "25,000"),
        ("4", "Anaesthetist Fee (Spinal)", "1", "6,000", "6,000"),
        ("5", "Senior Surgeon Fee (per day)", "4", "1,200", "4,800"),
        ("6", "OT Charges", "1", "12,000", "12,000"),
        ("7", "OT Consumables (IM Nail, screws, fluoroscopy)", "1", "16,000", "16,000"),
        ("8", "X-Ray Tibia-Fibula (AP/Lateral)", "2", "500", "1,000"),
        ("9", "CT Scan Leg (with 3D)", "1", "3,500", "3,500"),
        ("10", "Blood Tests (CBC, RBS, Coagulation)", "1", "1,500", "1,500"),
        ("11", "IV Tramadol, fluids, tetanus toxoid", "1", "2,200", "2,200"),
        ("12", "Oral Medicines at discharge", "1", "800", "800"),
        ("13", "Ambulance", "1", "800", "800"),
        ("14", "Plaster, dressing, crutches", "1", "1,200", "1,200"),
    ]
    for it in items:
        bill_data.append([Paragraph(it[0], style_cell), Paragraph(it[1], style_cell), Paragraph(it[2], style_cell), Paragraph(it[3], style_cell), Paragraph(it[4], style_cell)])
    t = Table(bill_data, colWidths=[10*mm, 65*mm, 12*mm, 22*mm, 26*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER_GRAY),
        ("BACKGROUND", (0, 1), (-1, -1), LIGHT_GRAY),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(t)
    story.append(sp())
    total = 101800
    gst = int(total * 0.18)
    story.append(Paragraph(f"<b>Sub Total: Rs. {total:,}</b>", style_body))
    story.append(Paragraph(f"GST @ 18%: Rs. {gst:,}", style_body))
    story.append(Paragraph(f"<b>GRAND TOTAL: Rs. {total + gst:,}</b>", style_body))
    story.append(sp(6))
    story.append(Paragraph(f"Generated: 14-Jun-2025", style_footer))
    doc.build(story)
    print(f"  Created: {os.path.join(SAMPLES_DIR, sub, 'hospital_bill.pdf')}")


# ===================================================================
# Test Case 3: REJECT — Pre-existing disease, within waiting period
# ===================================================================
def generate_test3():
    sub = "test3_reject"
    print(f"\n--- Test Case 3: REJECT (PED within waiting period) ---")

    # Discharge Summary
    doc = make_doc("discharge_summary.pdf", sub)
    story = []
    story.append(Paragraph("LIFECARE HOSPITAL", style_title))
    story.append(Paragraph("DISCHARGE SUMMARY", style_subtitle))
    story.append(hr())
    story.append(Paragraph("Patient Information", style_section))
    story.append(info_table([
        ("Patient Name", "Rajesh Kumar Sharma"),
        ("Age / Gender", "45 Years / Male"),
        ("Bed Number", "ICU-5"),
        ("Admission Number", "LC-2025-007721"),
        ("Date of Admission", "15-Jul-2025, 03:45 hrs (Emergency)"),
        ("Date of Discharge", "23-Jul-2025, 14:00 hrs"),
        ("Duration of Stay", "8 days (3 ICU, 5 ward)"),
        ("Attending Doctor", "Dr. Rakesh Verma, DM (Cardiology)"),
    ]))
    story.append(sp())
    story.append(Paragraph("History of Present Illness", style_section))
    story.append(Paragraph("Patient presented with sudden onset crushing chest pain since 14-Jul-2025 evening, radiating to left arm and jaw, associated with sweating and breathlessness. Known case of Diabetes Mellitus for 8 years and Hypertension for 12 years. Previously diagnosed with Ischemic Heart Disease in 2019. On regular medications (Tab. Metformin, Tab. Amlodipine, Tab. Clopidogrel). Non-compliant with medications for past 3 weeks.", style_body))
    story.append(sp())
    story.append(Paragraph("Investigations", style_section))
    story.append(Paragraph("ECG: ST elevation in leads II, III, aVF. ECHO: LVEF 42%, inferior wall hypokinesia. Troponin I: 12.4 ng/mL (normal <0.04). Haemoglobin: 11.2, WBC: 14,800, Random Blood Sugar: 285 mg/dL, Serum Creatinine: 1.4, Lipid Profile: Total Cholesterol 268, LDL 195, Triglycerides 240.", style_body))
    story.append(sp())
    story.append(Paragraph("Diagnosis", style_section))
    story.append(Paragraph("Final Diagnosis: Acute Inferior Wall Myocardial Infarction (ICD-10: I21.0) in a patient with known Diabetes Mellitus (ICD-10: E11.65), Hypertension (ICD-10: I10), and Ischemic Heart Disease (ICD-10: I25.10)", style_body))
    story.append(sp())
    story.append(Paragraph("Treatment Given", style_section))
    story.append(Paragraph("Day 1-2 (ICU): IV thrombolytics (Alteplase), dual antiplatelet therapy (Aspirin + Clopidogrel loading), IV nitroglycerin, beta-blockers, statins. ICU monitoring, continuous ECG telemetry.", style_body))
    story.append(Paragraph("Day 3: Coronary angiography performed. Triple vessel disease noted. PCI with DES stenting to RCA done. LVEF improved to 48%.", style_body))
    story.append(Paragraph("Day 4-8 (CCU/Ward): Optimized medical therapy. Cardiac rehabilitation started. Discharged in stable condition.", style_body))
    story.append(sp())
    story.append(Paragraph("Advice", style_section))
    advice = [
        "Continue dual antiplatelet therapy (Aspirin 75mg + Clopidogrel 75mg) for 12 months",
        "Statins lifelong (Atorvastatin 40mg)",
        "Beta-blockers (Bisoprolol 2.5mg)",
        "Strict diabetes and blood pressure control",
        "Cardiac follow-up in 1 week, stress test at 1 month",
        "No heavy exercise for 4 weeks",
    ]
    for a in advice:
        story.append(Paragraph(f"  {chr(8226)} {a}", style_body))
    story.append(sp(6))
    story.append(Paragraph("Dr. Rakesh Verma, DM (Cardiology)", style_body))
    story.append(Paragraph("Regd. No: DL-DM-23456", style_footer))
    doc.build(story)
    print(f"  Created: {os.path.join(SAMPLES_DIR, sub, 'discharge_summary.pdf')}")

    # Hospital Bill
    doc = make_doc("hospital_bill.pdf", sub)
    story = []
    story.append(Paragraph("LIFECARE HOSPITAL", style_title))
    story.append(Paragraph("ITEMIZED BILL", style_subtitle))
    story.append(hr())
    story.append(info_table([
        ("Bill No.", "LC-BILL-2025-011203"),
        ("Patient Name", "Rajesh Kumar Sharma"),
        ("Admission", "15-Jul-2025 to 23-Jul-2025 (8 days)"),
    ]))
    story.append(sp())
    story.append(Paragraph("Itemized Charges", style_section))
    bill_data = [["S.No.", "Description", "Qty", "Rate (Rs.)", "Amount (Rs.)"]]
    items = [
        ("1", "ICU Room (per day)", "3", "12,000", "36,000"),
        ("2", "CCU Room (per day)", "5", "7,000", "35,000"),
        ("3", "ICU Nursing (per day)", "3", "3,500", "10,500"),
        ("4", "CCU/Ward Nursing (per day)", "5", "800", "4,000"),
        ("5", "Cardiologist Fee", "1", "45,000", "45,000"),
        ("6", "ICU Consultant Fee (per day)", "3", "5,000", "15,000"),
        ("7", "Senior Consultant Fee (per day)", "8", "2,000", "16,000"),
        ("8", "PCI with DES Stent (RCA)", "1", "1,80,000", "1,80,000"),
        ("9", "OT / Cath Lab Charges", "1", "35,000", "35,000"),
        ("10", "Alteplase (thrombolytic)", "1", "22,000", "22,000"),
        ("11", "Echocardiography (TTE)", "2", "3,500", "7,000"),
        ("12", "ECG (12 Lead)", "5", "400", "2,000"),
        ("13", "Blood Tests (Troponin, CBC, LFT, KFT, Lipid)", "6", "2,500", "15,000"),
        ("14", "ICU Medicines (IV drip, inotropes, etc.)", "1", "38,000", "38,000"),
        ("15", "Ward Medicines (oral)", "1", "6,500", "6,500"),
        ("16", "Ambulance", "1", "3,500", "3,500"),
        ("17", "Oxygen, consumables, etc.", "1", "8,000", "8,000"),
    ]
    for it in items:
        bill_data.append([Paragraph(it[0], style_cell), Paragraph(it[1], style_cell), Paragraph(it[2], style_cell), Paragraph(it[3], style_cell), Paragraph(it[4], style_cell)])
    t = Table(bill_data, colWidths=[10*mm, 65*mm, 12*mm, 22*mm, 26*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK_BLUE), ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER_GRAY), ("BACKGROUND", (0, 1), (-1, -1), LIGHT_GRAY),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t)
    story.append(sp())
    total = 496500
    gst = int(total * 0.18)
    story.append(Paragraph(f"<b>Sub Total: Rs. {total:,}</b>", style_body))
    story.append(Paragraph(f"GST @ 18%: Rs. {gst:,}", style_body))
    story.append(Paragraph(f"<b>GRAND TOTAL: Rs. {total + gst:,}</b>", style_body))
    story.append(sp(6))
    story.append(Paragraph(f"Generated: 23-Jul-2025", style_footer))
    doc.build(story)
    print(f"  Created: {os.path.join(SAMPLES_DIR, sub, 'hospital_bill.pdf')}")


# ===================================================================
# Test Case 4: PARTIAL — High room rent, sub-limit on room-only items
# ===================================================================
def generate_test4():
    sub = "test4_partial"
    print(f"\n--- Test Case 4: PARTIAL (room rent over limit, sub-limit breach) ---")

    # Discharge Summary
    doc = make_doc("discharge_summary.pdf", sub)
    story = []
    story.append(Paragraph("GLOBAL HEALTH CITY", style_title))
    story.append(Paragraph("DISCHARGE SUMMARY", style_subtitle))
    story.append(hr())
    story.append(Paragraph("Patient Information", style_section))
    story.append(info_table([
        ("Patient Name", "Rajesh Kumar Sharma"),
        ("Age / Gender", "45 Years / Male"),
        ("Bed Number", "Deluxe Suite D-301"),
        ("Admission Number", "GHC-2025-004412"),
        ("Date of Admission", "05-Aug-2025, 11:00 hrs (Planned)"),
        ("Date of Discharge", "10-Aug-2025, 12:00 hrs"),
        ("Duration of Stay", "5 days"),
        ("Attending Doctor", "Dr. Rajesh Gupta, MS (Orthopedics)"),
    ]))
    story.append(sp())
    story.append(Paragraph("History of Present Illness", style_section))
    story.append(Paragraph("Patient presented with complaints of severe bilateral knee pain, stiffness, and restricted mobility for the past 2 years. Pain worsening progressively, especially during walking and stair climbing. X-ray knee (done 02-Aug-2025) showed severe osteoarthritis with joint space narrowing and bone-on-bone contact on the right side. Diagnosed with end-stage osteoarthritis of right knee. Patient opted for surgical management. Not a known diabetic or hypertensive.", style_body))
    story.append(sp())
    story.append(Paragraph("Investigations", style_section))
    story.append(Paragraph("Haemoglobin: 13.5 g/dL, WBC: 7,200, Blood Group: B+, Random Blood Sugar: 102, Serum Creatinine: 0.8, ESR: 22 mm/hr, CRP: 8 mg/L. X-Ray Knee AP/Lateral: Severe osteoarthritis, joint space obliteration, osteophytes. MRI Knee: Full-thickness cartilage loss, subchondral cysts.", style_body))
    story.append(sp())
    story.append(Paragraph("Diagnosis", style_section))
    story.append(Paragraph("Final Diagnosis: Severe Osteoarthritis of Right Knee (ICD-10: M17.11)", style_body))
    story.append(sp())
    story.append(Paragraph("Treatment Given", style_section))
    story.append(Paragraph("Day 1: Pre-operative preparation, physiotherapy assessment, cross-matched blood kept ready.", style_body))
    story.append(Paragraph("Day 2 (07-Aug-2025): Right Total Knee Replacement (Cemented) performed under Spinal Anaesthesia by Dr. Rajesh Gupta. Femoral and tibial components implanted (Zimmer Biomet, size medium). Intra-operative stability and range of motion satisfactory. Drains placed.", style_body))
    story.append(Paragraph("Day 3-5: IV analgesics, anti-coagulants (Enoxaparin), physiotherapy (ROM exercises, quadriceps strengthening). Drains removed on Day 4. Discharged with oral analgesics and walker.", style_body))
    story.append(sp())
    story.append(Paragraph("Advice", style_section))
    advice = [
        "Continue Tab. Ecosprin 150mg OD for 6 weeks (anti-coagulation)",
        "Tab. Naproxen 500mg SOS for pain",
        "Strict physiotherapy twice daily",
        "Weight-bearing as tolerated with walker for 4 weeks",
        "Follow up on 18-Aug-2025 with X-ray knee",
        "Histopathology: Synovial tissue — chronic inflammatory changes",
    ]
    for a in advice:
        story.append(Paragraph(f"  {chr(8226)} {a}", style_body))
    story.append(sp(6))
    story.append(Paragraph("Dr. Rajesh Gupta, MS (Orthopedics)", style_body))
    story.append(Paragraph("Regd. No: DL-MS-67891", style_footer))
    doc.build(story)
    print(f"  Created: {os.path.join(SAMPLES_DIR, sub, 'discharge_summary.pdf')}")

    # Hospital Bill
    doc = make_doc("hospital_bill.pdf", sub)
    story = []
    story.append(Paragraph("GLOBAL HEALTH CITY", style_title))
    story.append(Paragraph("ITEMIZED BILL", style_subtitle))
    story.append(hr())
    story.append(info_table([
        ("Bill No.", "GHC-BILL-2025-006678"),
        ("Patient Name", "Rajesh Kumar Sharma"),
        ("Admission", "05-Aug-2025 to 10-Aug-2025 (5 days)"),
    ]))
    story.append(sp())
    story.append(Paragraph("Itemized Charges", style_section))
    bill_data = [["S.No.", "Description", "Qty", "Rate (Rs.)", "Amount (Rs.)"]]
    items = [
        ("1", "Room Rent - Deluxe Suite (per day)", "5", "12,000", "60,000"),
        ("2", "Nursing Charges (per day)", "5", "1,500", "7,500"),
        ("3", "Surgeon Fee - Right Total Knee Replacement", "1", "85,000", "85,000"),
        ("4", "Anaesthetist Fee (Spinal)", "1", "8,000", "8,000"),
        ("5", "Senior Surgeon Fee (per day)", "5", "2,000", "10,000"),
        ("6", "OT Charges", "1", "20,000", "20,000"),
        ("7", "TKR Implant (Zimmer Biomet, cemented)", "1", "1,25,000", "1,25,000"),
        ("8", "MRI Knee (with contrast)", "1", "8,500", "8,500"),
        ("9", "X-Ray Knee (AP/Lateral)", "2", "500", "1,000"),
        ("10", "Blood Tests (CBC, ESR, CRP, blood group)", "1", "3,000", "3,000"),
        ("11", "Histopathology (synovial tissue)", "1", "3,000", "3,000"),
        ("12", "Pharmacy (IV + oral)", "1", "5,500", "5,500"),
        ("13", "Physiotherapy (per session)", "5", "1,500", "7,500"),
        ("14", "Ambulance", "1", "1,500", "1,500"),
        ("15", "Walker, dressings, miscellaneous", "1", "3,000", "3,000"),
    ]
    for it in items:
        bill_data.append([Paragraph(it[0], style_cell), Paragraph(it[1], style_cell), Paragraph(it[2], style_cell), Paragraph(it[3], style_cell), Paragraph(it[4], style_cell)])
    t = Table(bill_data, colWidths=[10*mm, 65*mm, 12*mm, 22*mm, 26*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK_BLUE), ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER_GRAY), ("BACKGROUND", (0, 1), (-1, -1), LIGHT_GRAY),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t)
    story.append(sp())
    total = 249000
    gst = int(total * 0.18)
    story.append(Paragraph(f"<b>Sub Total: Rs. {total:,}</b>", style_body))
    story.append(Paragraph(f"GST @ 18%: Rs. {gst:,}", style_body))
    story.append(Paragraph(f"<b>GRAND TOTAL: Rs. {total + gst:,}</b>", style_body))
    story.append(sp(6))
    story.append(Paragraph(f"Generated: 10-Aug-2025", style_footer))
    doc.build(story)
    print(f"  Created: {os.path.join(SAMPLES_DIR, sub, 'hospital_bill.pdf')}")


# ===================================================================
# Test Case 5: ESCALATE — Conflicting dates and procedures
# ===================================================================
def generate_test5():
    sub = "test5_escalate"
    print(f"\n--- Test Case 5: ESCALATE (conflicting info) ---")

    # Discharge Summary — says 3-day admission for simple appendectomy
    doc = make_doc("discharge_summary.pdf", sub)
    story = []
    story.append(Paragraph("NATIONAL TRAUMA CENTRE", style_title))
    story.append(Paragraph("DISCHARGE SUMMARY", style_subtitle))
    story.append(hr())
    story.append(Paragraph("Patient Information", style_section))
    story.append(info_table([
        ("Patient Name", "Rajesh Kumar Sharma"),
        ("Age / Gender", "35 Years / Male"),
        ("Bed Number", "Ward C-210"),
        ("Admission Number", "NTC-2025-009934"),
        ("Date of Admission", "01-Sep-2025, 22:00 hrs (Emergency)"),
        ("Date of Discharge", "03-Sep-2025, 14:00 hrs"),
        ("Duration of Stay", "2 days"),
        ("Attending Doctor", "Dr. Amit Joshi, MS (General Surgery)"),
    ]))
    story.append(sp())
    story.append(Paragraph("History of Present Illness", style_section))
    story.append(Paragraph("Patient presented with right iliac fossa pain for 18 hours, associated with low-grade fever and nausea. No vomiting. Tenderness in right iliac fossa, positive McBurney's point tenderness. No peritonism. No history of similar episodes.", style_body))
    story.append(sp())
    story.append(Paragraph("Investigations", style_section))
    story.append(Paragraph("WBC: 14,200 (Neutrophils 85%), CRP: 45 mg/L, USG Abdomen: Enlarged non-compressible appendix measuring 11mm diameter with periappendicular fat stranding. No abscess seen.", style_body))
    story.append(sp())
    story.append(Paragraph("Diagnosis", style_section))
    story.append(Paragraph("Final Diagnosis: Acute Uncomplicated Appendicitis (ICD-10: K35.9)", style_body))
    story.append(sp())
    story.append(Paragraph("Treatment Given", style_section))
    story.append(Paragraph("Day 1 (01-Sep-2025): Laparoscopic Appendectomy performed under General Anaesthesia by Dr. Amit Joshi. Appendix was inflamed but not gangrenosed. No perforation. 4 ports placed, appendix excised, stump secured. Drains not required. Intra-operative findings consistent with acute appendicitis.", style_body))
    story.append(Paragraph("Day 2 (03-Sep-2025): Oral diet started. Discharged in stable condition with oral analgesics and antibiotics.", style_body))
    story.append(sp())
    story.append(Paragraph("Advice", style_section))
    advice = [
        "Continue Tab. Amoxicillin-Clavulanate 625mg for 3 more days",
        "Light activity only for 1 week",
        "Wound care: keep dry for 5 days",
        "Report if fever or wound discharge develops",
        "Histopathology: Acute suppurative appendicitis",
    ]
    for a in advice:
        story.append(Paragraph(f"  {chr(8226)} {a}", style_body))
    story.append(sp(6))
    story.append(Paragraph("Dr. Amit Joshi, MS (General Surgery)", style_body))
    story.append(Paragraph("Regd. No: DL-MS-34567", style_footer))
    doc.build(story)
    print(f"  Created: {os.path.join(SAMPLES_DIR, sub, 'discharge_summary.pdf')}")

    # Hospital Bill — says 7-day stay with ICU, multiple procedures (CONFLICT!)
    doc = make_doc("hospital_bill.pdf", sub)
    story = []
    story.append(Paragraph("NATIONAL TRAUMA CENTRE", style_title))
    story.append(Paragraph("ITEMIZED BILL", style_subtitle))
    story.append(hr())
    story.append(info_table([
        ("Bill No.", "NTC-BILL-2025-014455"),
        ("Patient Name", "Rajesh Kumar Sharma"),
        ("Admission Number", "NTC-2025-009934"),
        ("Admission Date", "01-Sep-2025"),
        ("Discharge Date", "08-Sep-2025"),
        ("Duration", "7 Days (2 ICU + 5 Ward)"),
    ]))
    story.append(sp())
    story.append(Paragraph("Itemized Charges", style_section))
    bill_data = [["S.No.", "Description", "Qty", "Rate (Rs.)", "Amount (Rs.)"]]
    items = [
        ("1", "Room Rent - ICU (per day)", "2", "18,000", "36,000"),
        ("2", "Room Rent - AC Ward (per day)", "5", "6,000", "30,000"),
        ("3", "ICU Nursing (per day)", "2", "4,000", "8,000"),
        ("4", "Ward Nursing (per day)", "5", "1,000", "5,000"),
        ("5", "Surgeon Fee - Laparoscopic Appendectomy + Laparoscopic Cholecystectomy", "1", "65,000", "65,000"),
        ("6", "Anaesthetist Fee", "1", "15,000", "15,000"),
        ("7", "ICU Consultant (per day)", "2", "6,000", "12,000"),
        ("8", "Senior Surgeon (per day)", "7", "2,500", "17,500"),
        ("9", "OT Charges - Laparoscopic (double procedure)", "1", "35,000", "35,000"),
        ("10", "OT Consumables", "1", "22,000", "22,000"),
        ("11", "CT Scan Abdomen (with contrast)", "1", "5,500", "5,500"),
        ("12", "X-Ray Chest (PA)", "2", "500", "1,000"),
        ("13", "Blood Tests", "1", "6,000", "6,000"),
        ("14", "ICU Medicines", "1", "28,000", "28,000"),
        ("15", "Ward Medicines", "1", "5,500", "5,500"),
        ("16", "Histopathology (appendix + gallbladder)", "1", "5,000", "5,000"),
        ("17", "Ambulance", "1", "2,000", "2,000"),
        ("18", "Oxygen, consumables", "1", "6,000", "6,000"),
    ]
    for it in items:
        bill_data.append([Paragraph(it[0], style_cell), Paragraph(it[1], style_cell), Paragraph(it[2], style_cell), Paragraph(it[3], style_cell), Paragraph(it[4], style_cell)])
    t = Table(bill_data, colWidths=[10*mm, 65*mm, 12*mm, 22*mm, 26*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK_BLUE), ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER_GRAY), ("BACKGROUND", (0, 1), (-1, -1), LIGHT_GRAY),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t)
    story.append(sp())
    total = 264500
    gst = int(total * 0.18)
    story.append(Paragraph(f"<b>Sub Total: Rs. {total:,}</b>", style_body))
    story.append(Paragraph(f"GST @ 18%: Rs. {gst:,}", style_body))
    story.append(Paragraph(f"<b>GRAND TOTAL: Rs. {total + gst:,}</b>", style_body))
    story.append(sp(6))
    story.append(Paragraph(f"Generated: 08-Sep-2025", style_footer))
    doc.build(story)
    print(f"  Created: {os.path.join(SAMPLES_DIR, sub, 'hospital_bill.pdf')}")


# ===================================================================
# Copy the same policy cert to all test case dirs
# ===================================================================
def copy_policy_to_testcases():
    import shutil
    src = os.path.join(SAMPLES_DIR, "ir dai_policy_certificate.pdf")
    if not os.path.exists(src):
        print(f"\nWarning: Policy certificate not found at {src}. Skipping copy.")
        return
    for sub in ["test2_approve", "test3_reject", "test4_partial", "test5_escalate"]:
        dst = os.path.join(SAMPLES_DIR, sub, "ir dai_policy_certificate.pdf")
        os.makedirs(os.path.join(SAMPLES_DIR, sub), exist_ok=True)
        shutil.copy2(src, dst)
    print(f"\nCopied policy certificate to all 4 test case directories.")


# ===================================================================
# Main
# ===================================================================
if __name__ == "__main__":
    print("Generating 4 test case PDF sets...")
    print(f"Output: {SAMPLES_DIR}/test*_")
    generate_test2()
    generate_test3()
    generate_test4()
    generate_test5()
    copy_policy_to_testcases()
    print("\nDone! Expected verdicts:")
    print("  test2_approve  -> APPROVE  (accident, room rent within limit, all covered)")
    print("  test3_reject   -> REJECT   (PED within 48-month waiting period)")
    print("  test4_partial  -> PARTIAL  (room rent 12K/day >> 5K limit, co-pay)")
    print("  test5_escalate -> ESCALATE (discharge says 2 days, bill says 7 days; extra procedures on bill)")
