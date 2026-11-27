from pathlib import Path
import csv
from openpyxl import Workbook
import pymupdf as fitz

OUT = Path(__file__).resolve().parents[1] / "data" / "sample_documents"
OUT.mkdir(parents=True, exist_ok=True)

def workbook(filename, sheet, headers, rows):
    wb=Workbook(); ws=wb.active; ws.title=sheet; ws.append(headers)
    for row in rows: ws.append(row)
    wb.save(OUT/filename)

workbook("ERP packaging BOM.xlsx","BOM",["Component ID","Product ID","Component","Material","Weight (g)","Supplier ID","Recycled content (%)","PCR content (%)"],[
    ["PKG-001","PRD-001","Corrugated outer box","Paper",420,"SUP-001",85,65],
    ["PKG-002","PRD-001","Molded pulp insert","Paper",85,"SUP-001",70,55],
    ["PKG-003","PRD-001","Protective tray","Virgin PET",25,"SUP-002",30,30],
    ["PKG-004","PRD-001","Protective bag","LDPE",18.5,"SUP-002",0,0],
    ["PKG-005","PRD-001","Instruction leaflet","Paper",12,"SUP-001",100,80],
    ["PKG-006","PRD-001","Product label","Paper + acrylic adhesive",3.2,"SUP-003",0,0],
])
workbook("Packaging specification.xlsx","S1 Spec",["Component ID","Component","Dimensions","Mass (kg)","Function","Market"],[
    ["PKG-001","Outer box","290 x 220 x 125 mm",0.420,"Transit protection","EU"],
    ["PKG-003","Protective tray","245 x 175 x 30 mm",0.025,"Product restraint","EU"],
    ["PKG-004","Protective bag","250 x 180 x 80 mm",0.0185,"Dust protection","EU"],
])
workbook("Supplier material matrix.xlsx","Materials",["Component ID","Supplier","Material","Grade","Declaration date","Recyclability evidence"],[
    ["PKG-001","NordPak Fibre GmbH","Paper","Corrugated board 32 ECT","2026-03-12","Collection dependent"],
    ["PKG-003","ReForm Polymers BV","Recycled PET","Clear tray grade","2026-04-05","Not provided"],
    ["PKG-004","ReForm Polymers BV","Plastic","LDPE film","2026-04-05","Not provided"],
])
with (OUT/"Packaging dimensions.csv").open("w",newline="",encoding="utf-8") as f:
    w=csv.writer(f); w.writerow(["Component ID","Component","Length mm","Width mm","Height mm"])
    w.writerows([["PKG-001","Outer box",290,220,125],["PKG-003","PET tray",245,175,30],["PKG-004","LDPE bag",250,180,80]])

def pdf(name, title, paragraphs):
    doc=fitz.open(); p=doc.new_page(); y=60
    p.insert_text((54,y),title,fontsize=19,color=(.1,.3,.24)); y+=34
    p.insert_text((54,y),"EcoNova Consumer Electronics · Synthetic demonstration evidence",fontsize=9,color=(.3,.4,.4)); y+=32
    for para in paragraphs:
        p.insert_textbox(fitz.Rect(54,y,535,y+88),para,fontsize=11,lineheight=1.4); y+=104
    doc.save(OUT/name)

pdf("Supplier declarations.pdf","Supplier Declaration — Fibre Packaging",[
    "Supplier: NordPak Fibre GmbH. Declaration date: 12 March 2026. Packaging component PKG-001: corrugated board, 85% recycled fibre by supplier declaration. PCR fibre content reported as 65%.",
    "Component PKG-002: molded paper fibre insert. Recycled fibre content reported as 70%. Components are designed for fibre recovery where local collection and sorting accept the format. This statement is not a legal recyclability certification.",
])
pdf("Recycled content certificate.pdf","Material Certificate — PET Tray",[
    "Supplier: ReForm Polymers BV. Certificate reference: RF-2026-041. Component reference PKG-003. Clear PET tray resin includes 30% post-consumer recycled content by mass for the stated production batch.",
    "This supplier certificate is a synthetic sample. The ERP bill of materials currently states Virgin PET. Confirm batch scope and effective date before changing the master material record.",
])
pdf("Chemical disclosure declaration.pdf","Chemical Disclosure — Label Components",[
    "Supplier: ClearMark Labels Ltd. Product reference PKG-006, paper label with acrylic adhesive. Declaration status: pending technical review. Adhesive formulation and substance-level supporting annex were not included in this sample.",
    "No conclusion on restricted substances can be made from this pending declaration. Request current supporting documentation and record the reviewer decision.",
])
pdf("Supplier declaration - LDPE film.pdf","Supplier Statement — Protective Film",[
    "Supplier: ReForm Polymers BV. Component PKG-004 protective bag. Material stated as LDPE film. Component mass 18.5 g (0.0185 kg) per specification. Recycled-content claim: 0% in ERP sample record.",
    "End-of-life behavior depends on market collection, sorting, and the overall package design. No recyclability evidence supplied.",
])
pdf("Packaging design note.pdf","Packaging Engineering Design Note",[
    "EcoNova Smart Speaker S1 dimensions 205 × 135 × 105 mm. Outer carton dimensions 290 × 220 × 125 mm. Inner fit is an initial geometry screen only; protective clearance, drop testing, and pack-out efficiency must be validated before a design change.",
    "Current outer box mass is 420 g; molded fibre insert mass is 85 g; PET tray mass is 25 g. Candidate mass changes are illustrative and require packaging qualification.",
])

# A small, labeled synthetic fixture image for exercising the image upload path.
try:
    from PIL import Image, ImageDraw, ImageFont
    image=Image.new("RGB",(1200,650),"white"); draw=ImageDraw.Draw(image)
    draw.rectangle((45,45,1150,605),outline=(35,96,75),width=4)
    draw.text((80,90),"ECONOVA SMART SPEAKER S1",fill=(24,63,52))
    draw.text((80,160),"PACKAGING SPECIFICATION · SYNTHETIC DEMO",fill=(25,102,112))
    draw.text((80,260),"Protective tray | PET | 25 g | PCR 30%",fill=(35,45,50))
    draw.text((80,320),"Tray dimensions: 245 x 175 x 30 mm",fill=(35,45,50))
    draw.text((80,380),"Supplier certificate: ReForm Polymers BV",fill=(35,45,50))
    draw.text((80,505),"TRAINING FIXTURE — NOT A REAL PRODUCT LABEL",fill=(150,72,38))
    image.save(OUT/"S1 packaging photo.png")
except ImportError: pass
print(f"Created sample evidence in {OUT}")
