from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SAMPLES = DATA / "sample_documents"
UPLOADS = DATA / "uploads"
DB = DATA / "packtrace.db"
DATA.mkdir(exist_ok=True)
SAMPLES.mkdir(exist_ok=True)
UPLOADS.mkdir(exist_ok=True)

app = FastAPI(title="PackTrace AI", version="1.0.0", description="Evidence-grounded packaging data readiness POC")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@contextmanager
def connect():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def now():
    return datetime.now().isoformat(timespec="seconds")


def init_db():
    with connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS products(id TEXT PRIMARY KEY, name TEXT, group_name TEXT, market TEXT, description TEXT);
        CREATE TABLE IF NOT EXISTS suppliers(id TEXT PRIMARY KEY, name TEXT, location TEXT, email TEXT, status TEXT);
        CREATE TABLE IF NOT EXISTS components(id TEXT PRIMARY KEY, product_id TEXT REFERENCES products(id), name TEXT, level TEXT, function TEXT, material TEXT, grade TEXT, weight_g REAL, recycled_pct REAL, pcr_pct REAL, dimensions TEXT, supplier_id TEXT REFERENCES suppliers(id), country TEXT, recyclable TEXT, reuse TEXT, chemical TEXT, owner TEXT, updated TEXT, verification TEXT, attributes TEXT, history TEXT);
        CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, name TEXT, kind TEXT, status TEXT, uploaded TEXT, size INTEGER, summary TEXT);
        CREATE TABLE IF NOT EXISTS evidence(id TEXT PRIMARY KEY, component_id TEXT, attribute TEXT, value TEXT, unit TEXT, document_id TEXT, filename TEXT, location TEXT, method TEXT, confidence REAL, review TEXT);
        CREATE TABLE IF NOT EXISTS conflicts(id TEXT PRIMARY KEY, component_id TEXT, attribute TEXT, source_a TEXT, value_a TEXT, source_b TEXT, value_b TEXT, severity TEXT, explanation TEXT, recommendation TEXT, status TEXT, resolution TEXT, note TEXT, updated TEXT);
        CREATE TABLE IF NOT EXISTS findings(id TEXT PRIMARY KEY, component_id TEXT, area TEXT, title TEXT, requirement TEXT, applicability TEXT, result TEXT, severity TEXT, action TEXT, evidence TEXT, confidence REAL, due TEXT, reviewed TEXT);
        CREATE TABLE IF NOT EXISTS roadmap(id TEXT PRIMARY KEY, year INTEGER, title TEXT, description TEXT, department TEXT, priority TEXT, due TEXT, status TEXT, finding TEXT);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT, entity TEXT, entity_id TEXT, detail TEXT, created TEXT);
        CREATE TABLE IF NOT EXISTS scenarios(id TEXT PRIMARY KEY, name TEXT, input TEXT, result TEXT, created TEXT);
        """)
        if c.execute("SELECT count(*) FROM products").fetchone()[0]:
            # Keep sample finding references aligned with the evidence records, including
            # workspaces seeded by an earlier POC build.
            sample_refs=[
                ("EV-001","PKG-001","weight_g","420","DOC-001"),("EV-002","PKG-001","material","Paper","DOC-003"),
                ("EV-003","PKG-003","material","Virgin PET","DOC-001"),("EV-004","PKG-003","material","Recycled PET","DOC-004"),
                ("EV-005","PKG-003","pcr_pct","30","DOC-004"),("EV-006","PKG-004","weight_g","0.0185","DOC-002"),
                ("EV-007","PKG-004","weight_g","18.5","DOC-001"),("EV-008","PKG-004","pcr_pct","0","DOC-001"),
                ("EV-009","PKG-006","chemical","Pending","DOC-005"),("EV-010","PKG-002","weight_g","85","DOC-001"),
            ]
            for eid,cid,attr,value,did in sample_refs:
                old=c.execute("SELECT id FROM evidence WHERE component_id=? AND attribute=? AND value=? AND document_id=? LIMIT 1",(cid,attr,value,did)).fetchone()
                if old: c.execute("UPDATE evidence SET id=? WHERE id=?",(eid,old[0]))
            for fid,cid in c.execute("SELECT id,component_id FROM findings").fetchall():
                ev=c.execute("SELECT id FROM evidence WHERE component_id=? ORDER BY id LIMIT 1",(cid,)).fetchone()
                c.execute("UPDATE findings SET evidence=? WHERE id=?",(ev[0] if ev else "",fid))
            return
        products = [
            ("PRD-001", "EcoNova Smart Speaker S1", "Consumer electronics", "EU", "Connected home audio"),
            ("PRD-002", "EcoNova Home Hub Mini", "Consumer electronics", "EU", "Compact smart-home controller"),
            ("PRD-003", "EcoNova Soundbar Air", "Consumer electronics", "EU", "Wireless home soundbar"),
        ]
        suppliers = [
            ("SUP-001", "NordPak Fibre GmbH", "Hamburg, Germany", "sustainability@nordpak.example", "Active"),
            ("SUP-002", "ReForm Polymers BV", "Rotterdam, Netherlands", "compliance@reform.example", "Active"),
            ("SUP-003", "ClearMark Labels Ltd.", "Leeds, United Kingdom", "data@clearmark.example", "Review needed"),
            ("SUP-004", "PackRight Components Sp. z o.o.", "Poznań, Poland", "quality@packright.example", "Active"),
        ]
        c.executemany("INSERT INTO products VALUES(?,?,?,?,?)", products)
        c.executemany("INSERT INTO suppliers VALUES(?,?,?,?,?)", suppliers)
        dataset = [
            ("PKG-001","PRD-001","Corrugated outer box","Secondary","Transit protection","Paper","Corrugated board 32 ECT",420,85,65,"290 × 220 × 125 mm","SUP-001","DE","Collection dependent","No","Available","L. Fischer", "Verified"),
            ("PKG-002","PRD-001","Molded pulp insert","Secondary","Cushioning","Paper","Molded fibre",85,70,55,"260 × 190 × 48 mm","SUP-001","DE","Collection dependent","No","Available","L. Fischer", "Verified"),
            ("PKG-003","PRD-001","Protective tray","Secondary","Product restraint","Plastic","PET, clear",25,30,30,"245 × 175 × 30 mm","SUP-002","NL","Unverified","No","Pending","M. Chen", "Conflict"),
            ("PKG-004","PRD-001","Protective bag","Primary","Dust protection","Plastic","LDPE",18.5,0,0,"250 × 180 × 80 mm","SUP-002","NL","Unverified","No","Not declared","M. Chen", "Needs review"),
            ("PKG-005","PRD-001","Instruction leaflet","Primary","Consumer information","Paper","Uncoated paper",12,100,80,"148 × 210 mm","SUP-001","DE","Collection dependent","No","Available","L. Fischer", "Verified"),
            ("PKG-006","PRD-001","Product label","Primary","Identification","Paper","Paper label + acrylic adhesive",3.2,0,0,"60 × 35 mm","SUP-003","GB","Unverified","No","Pending","A. Patel", "Needs review"),
            ("PKG-007","PRD-002","Folding carton","Secondary","Transit protection","Paper","Folding boxboard",180,80,60,"180 × 140 × 95 mm","SUP-001","DE","Collection dependent","No","Available","L. Fischer", "Verified"),
            ("PKG-008","PRD-002","Fibre end caps","Secondary","Cushioning","Paper","Molded fibre",42,70,50,"165 × 125 × 40 mm","SUP-001","DE","Collection dependent","No","Available","L. Fischer", "Verified"),
            ("PKG-009","PRD-002","Cable sleeve","Primary","Cable protection","Plastic","PE blend",9,0,0,"160 × 60 mm","SUP-002","NL","Unverified","No","Not declared","M. Chen", "Needs review"),
            ("PKG-010","PRD-002","Quick start guide","Primary","Consumer information","Paper","Uncoated paper",8,100,80,"105 × 148 mm","SUP-001","DE","Collection dependent","No","Available","L. Fischer", "Verified"),
            ("PKG-011","PRD-002","Security seal","Primary","Tamper evidence","Plastic","PP",1.5,0,0,"25 × 12 mm","SUP-003","GB","Unverified","No","Pending","A. Patel", "Needs review"),
            ("PKG-012","PRD-003","Shipping carton","Tertiary","Pallet transport","Paper","Double-wall corrugated",690,80,55,"820 × 160 × 140 mm","SUP-001","DE","Collection dependent","No","Available","L. Fischer", "Verified"),
            ("PKG-013","PRD-003","Pulp side supports","Secondary","Cushioning","Paper","Molded fibre",160,65,45,"380 × 95 × 75 mm","SUP-001","DE","Collection dependent","No","Available","L. Fischer", "Verified"),
            ("PKG-014","PRD-003","Polyolefin sleeve","Primary","Surface protection","Plastic","PE",28,20,20,"760 × 140 mm","SUP-002","NL","Unverified","No","Pending","M. Chen", "Needs review"),
            ("PKG-015","PRD-003","Accessory pouch","Secondary","Cable organization","Plastic","PET",16,0,0,"170 × 120 mm","SUP-004","PL","Unverified","No","Not declared","M. Chen", "Needs review"),
        ]
        for row in dataset:
            (cid,pid,name,level,fn,mat,grade,w,rc,pcr,dims,sid,country,recy,reuse,chem,owner,ver) = row
            attr = {"product_dimensions": "205 × 135 × 105 mm" if pid=="PRD-001" else "130 × 90 × 55 mm" if pid=="PRD-002" else "780 × 125 × 115 mm", "data_completeness": 89 if cid in ["PKG-001","PKG-002","PKG-005","PKG-007","PKG-008","PKG-010","PKG-012","PKG-013"] else 68, "risk": 2 if ver=="Verified" else 4}
            c.execute("INSERT INTO components VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (cid,pid,name,level,fn,mat,grade,w,rc,pcr,dims,sid,country,recy,reuse,chem,owner,(date.today()-timedelta(days=8 if ver=="Verified" else 47)).isoformat(),ver,json.dumps(attr),"[]"))
        docs = [
            ("DOC-001","ERP packaging BOM.xlsx","Spreadsheet","Processed",12040,"ERP component master export; includes packaging BOM weights and material codes."),
            ("DOC-002","Packaging specification.xlsx","Spreadsheet","Processed",8640,"Packaging engineering specification; dimensions and functional requirements."),
            ("DOC-003","Supplier declarations.pdf","PDF","Processed",39120,"NordPak fibre packaging declaration; supplier-reported material and recycled content."),
            ("DOC-004","Recycled content certificate.pdf","PDF","Processed",28760,"ReForm Polymers certificate; PET tray PCR content declared at 30%."),
            ("DOC-005","Chemical disclosure declaration.pdf","PDF","Processed",22100,"Supplier chemical disclosure status for selected components."),
            ("DOC-006","Packaging dimensions.csv","CSV","Processed",1260,"Measured outer dimensions for S1 packaging assembly."),
            ("DOC-007","Supplier material matrix.xlsx","Spreadsheet","Processed",7340,"Supplier material matrix with format and end-of-life notes."),
            ("DOC-008","S1 packaging photo.png","Image","Processed",48200,"Synthetic sample image record; OCR evidence not present in original POC fixture."),
        ]
        c.executemany("INSERT INTO documents VALUES(?,?,?,?,?,?,?)", [(d[0],d[1],d[2],d[3],now(),d[4],d[5]) for d in docs])
        evidence = [
            ("EV-001","PKG-001","weight_g","420","g","DOC-001","ERP packaging BOM.xlsx","Sheet BOM · cell F4","Spreadsheet cell",.99,"Verified"),
            ("EV-002","PKG-001","material","Paper","","DOC-003","Supplier declarations.pdf","Page 2 · paragraph 3","PDF text",.95,"Verified"),
            ("EV-003","PKG-003","material","Virgin PET","","DOC-001","ERP packaging BOM.xlsx","Sheet BOM · cell D6","Spreadsheet cell",.99,"Open"),
            ("EV-004","PKG-003","material","Recycled PET","","DOC-004","Recycled content certificate.pdf","Page 1 · statement 2","PDF text",.94,"Open"),
            ("EV-005","PKG-003","pcr_pct","30","%","DOC-004","Recycled content certificate.pdf","Page 1 · statement 2","PDF text",.94,"Reviewed"),
            ("EV-006","PKG-004","weight_g","0.0185","kg","DOC-002","Packaging specification.xlsx","Sheet S1 · cell C9","Spreadsheet cell",.98,"Reviewed"),
            ("EV-007","PKG-004","weight_g","18.5","g","DOC-001","ERP packaging BOM.xlsx","Sheet BOM · cell F7","Spreadsheet cell",.99,"Reviewed"),
            ("EV-008","PKG-004","pcr_pct","0","%","DOC-001","ERP packaging BOM.xlsx","Sheet BOM · cell H7","Spreadsheet cell",.97,"Open"),
            ("EV-009","PKG-006","chemical","Pending","","DOC-005","Chemical disclosure declaration.pdf","Page 1 · section 4","PDF text",.90,"Open"),
            ("EV-010","PKG-002","weight_g","85","g","DOC-001","ERP packaging BOM.xlsx","Sheet BOM · cell F5","Spreadsheet cell",.99,"Verified"),
        ]
        c.executemany("INSERT INTO evidence VALUES(?,?,?,?,?,?,?,?,?,?,?)", evidence)
        conflicts = [
            ("CON-001","PKG-003","material","ERP packaging BOM.xlsx","Virgin PET","Recycled content certificate.pdf","Recycled PET","High","ERP master describes virgin resin while supplier certificate describes recycled PET. Confirm whether grade changed or records refer to different lots.","Verify certificate scope, then update the component grade and retain the dated ERP value."),
            ("CON-002","PKG-004","weight_g","Packaging specification.xlsx","0.0185 kg","ERP packaging BOM.xlsx","18.5 g","Low","Values are equivalent after unit normalization (0.0185 kg = 18.5 g); this is a unit mismatch, not a substantive conflict.","Confirm canonical unit in ERP; no quantity correction required."),
            ("CON-003","PKG-006","chemical","ERP packaging BOM.xlsx","Declaration missing","Chemical disclosure declaration.pdf","Pending review","Medium","Chemical status differs because the supplier statement is not yet reviewed and the ERP field is blank.","Request a current declaration and have the owner review the supplier evidence."),
        ]
        c.executemany("INSERT INTO conflicts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [(x[0],*x[1:11],"Open","","",now()) for x in conflicts])
        finding_rows = [
            ("PKG-003","Recycled content","Validate PET tray PCR claim","Plastic recycled-content target requires format-specific applicability and verified supplier evidence.","Plastic component; target basis requires jurisdiction and format review.","Evidence gap","High","Confirm certificate scope and map the tray to the applicable target category."),
            ("PKG-004","Design for recycling","Assess LDPE bag recyclability","Material alone does not demonstrate recyclability; local collection and component design evidence are missing.","Plastic film; market collection assumptions must be configured.","Needs assessment","Medium","Obtain design/end-market evidence and record intended market assumptions."),
            ("PKG-006","Chemical disclosure","Complete adhesive disclosure","Adhesive chemistry and applicable restricted-substance evidence have not been reviewed.","Adhesive component; substance-level declaration required for assessment.","Evidence gap","High","Request current adhesive disclosure and record review decision."),
            ("PKG-001","Minimization","Review outer carton headspace","Outer box volume is larger than product dimensions; fit and protection assessment is needed before reduction.","Screening proxy only; protection testing is required.","Opportunity","Medium","Run a protective fit trial before reducing board or dimensions."),
            ("PKG-003","Minimization","Consider PET tray mass reduction","Component has measurable mass; design and transit requirements are not captured.","No legal threshold implied.","Opportunity","Low","Compare a lighter geometry while validating drop performance."),
            ("PKG-009","Supplier evidence","Obtain cable sleeve declaration","Material blend and recycled content are not supported by reviewed supplier evidence.","Supplier evidence missing.","Evidence gap","Medium","Request composition, recycled content, and end-of-life declaration."),
            ("PKG-011","Material composition","Clarify security seal substrate","Seal material is recorded but adhesive and separation behavior are unknown.","Small component; screen based on total package design.","Needs assessment","Low","Add construction details to the specification."),
            ("PKG-014","Empty space","Review soundbar shipping fit","Dimension data indicates an opportunity for fit validation; no protection data is linked.","Screening calculation uses rectangular bounds.","Opportunity","Medium","Measure the packed assembly and validate protective performance."),
            ("PKG-015","Supplier traceability","Request pouch composition","PET grade and origin evidence are not attached.","Supplier declaration needed.","Evidence gap","Medium","Request current material declaration and certificate."),
            ("PKG-005","Evidence quality","Confirm recycled-content evidence date","ERP indicates recycled content but no source certificate is attached to the component record.","Supplier claim is unverified in this sample.","Evidence gap","Low","Attach a current supplier certificate."),
            ("PKG-012","Minimization","Assess tertiary carton optimization","Large format may allow nesting or pallet efficiency gains; evaluate with logistics data.","Optimization estimate excludes transport damage and pallet constraints.","Opportunity","Low","Model load pattern before changing carton size."),
        ]
        for i, row in enumerate(finding_rows,1):
            comp,area,title,req,applic,result,severity,action=row
            ev=c.execute("SELECT id FROM evidence WHERE component_id=? ORDER BY id LIMIT 1",(comp,)).fetchone()
            c.execute("INSERT INTO findings VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (f"FND-{i:03d}",comp,area,title,req,applic,result,severity,action,ev[0] if ev else "",.72 if severity in ("High","Medium") else .84,"2027-06-30","Open"))
        tasks = [
            (2026,"Establish packaging data baseline","Confirm product-component hierarchy, attribute owners, and required data schema.","Data & Sustainability","High","2026-12-15","In progress","FND-001"),
            (2026,"Resolve priority source conflicts","Review conflicting material and disclosure records with evidence owners.","Packaging Engineering","High","2026-12-22","Open","CON-001"),
            (2027,"Collect supplier declarations","Request composition, recycled content, and chemical evidence from priority suppliers.","Procurement","High","2027-05-30","Open","FND-006"),
            (2027,"Review evidence freshness","Set expiry and review cadence for supplier claims and certificates.","Quality","Medium","2027-09-30","Open","FND-010"),
            (2028,"Configure market-specific assessment rules","Validate applicable recyclability and recycled-content criteria with counsel.","Legal & Compliance","High","2028-06-30","Open","FND-002"),
            (2028,"Document packaging protection criteria","Capture transit, product safety, and performance constraints for designs.","Packaging Engineering","Medium","2028-12-15","Open","FND-004"),
            (2029,"Prioritize material optimization trials","Run protection-validated trials for shortlisted component opportunities.","Product Design","Medium","2029-06-30","Open","FND-005"),
            (2029,"Plan supplier change implementation","Align qualification and production timing for approved material changes.","Operations","Medium","2029-12-15","Open","FND-011"),
            (2030,"Maintain target-date readiness review","Refresh data, evidence, applicability, and assessment conclusions.","Sustainability","High","2030-01-31","Open","FND-001"),
        ]
        for i,t in enumerate(tasks,1): c.execute("INSERT INTO roadmap VALUES(?,?,?,?,?,?,?,?,?)",(f"TASK-{i:03d}",*t))


def rows(sql, params=()):
    with connect() as c: return [dict(x) for x in c.execute(sql, params).fetchall()]


def component(cid):
    r=rows("SELECT c.*,p.name product,p.group_name,s.name supplier,s.id supplier_code FROM components c JOIN products p ON p.id=c.product_id LEFT JOIN suppliers s ON s.id=c.supplier_id WHERE c.id=?",(cid,))
    if not r: raise HTTPException(404,"Packaging component not found")
    x=r[0]; x["attributes"]=json.loads(x["attributes"]); x["history"]=json.loads(x["history"]); x["evidence"]=rows("SELECT * FROM evidence WHERE component_id=?",(cid,)); x["findings"]=rows("SELECT * FROM findings WHERE component_id=?",(cid,)); return x


def metrics():
    comps=rows("SELECT * FROM components"); conf=rows("SELECT * FROM conflicts WHERE status IN ('Open','Under review')"); f=rows("SELECT * FROM findings WHERE reviewed='Open'")
    total=len(comps); complete=sum(json.loads(x["attributes"])["data_completeness"] for x in comps)/max(total,1)
    evidence=rows("SELECT count(DISTINCT component_id) n FROM evidence WHERE component_id<>''")[0]["n"]
    evcover=100*evidence/max(total,1); consistency=100*max(0,total-len(conf))/max(total,1)
    suppliers=rows("SELECT count(DISTINCT e.component_id) n FROM evidence e JOIN documents d ON d.id=e.document_id WHERE d.kind='PDF'")[0]["n"]; trace=100*suppliers/max(total,1)
    assess=100*(len(comps)-min(len(f),len(comps))*.45)/max(len(comps),1)
    vals={"completeness":round(complete,1),"evidence_coverage":round(min(evcover,100),1),"consistency":round(consistency,1),"supplier_traceability":round(trace,1),"assessment_coverage":round(assess,1)}
    defaults={"completeness":.30,"evidence_coverage":.25,"consistency":.20,"supplier_traceability":.15,"assessment_coverage":.10}
    try:
        weights=json.loads((DATA/"scoring.json").read_text(encoding="utf-8"))
        if set(weights)!=set(defaults) or any(float(v)<0 for v in weights.values()) or abs(sum(weights.values())-1)>0.0001: raise ValueError("Invalid scoring weights")
        weights={k:float(v) for k,v in weights.items()}
    except (OSError,ValueError,TypeError,json.JSONDecodeError): weights=defaults
    score=round(sum(vals[k]*v for k,v in weights.items()),1)
    return {"score":score,"components":total,"metrics":vals,"weights":weights,"open_conflicts":len(conf),"high_findings":sum(1 for x in f if x["severity"] in ["Critical","High"]),"total_weight_g":round(sum(x["weight_g"] or 0 for x in comps),1),"recycled_content_readiness":round(sum(x["recycled_pct"] or 0 for x in comps)/max(total,1),1),"optimization_potential_g":round(sum((x["weight_g"] or 0)*.12 for x in comps),1),"findings":f,"conflicts":conf}


@app.get("/api/config/scoring")
def scoring_config(): return {"weights":metrics()["weights"],"note":"Edit data/scoring.json; weights must be non-negative and sum to 1."}


def log(event, entity, entity_id, detail):
    with connect() as c: c.execute("INSERT INTO audit(event,entity,entity_id,detail,created) VALUES(?,?,?,?,?)",(event,entity,entity_id,detail,now()))


class EditPayload(BaseModel):
    field: str
    value: Any
    note: str = "User correction"

class ResolvePayload(BaseModel):
    value: str = ""
    source: str = ""
    note: str = Field(default="", max_length=1000)
    status: str = "Resolved"

class ReviewPayload(BaseModel):
    reviewed: str = "Reviewed"
    note: str = ""

class SimPayload(BaseModel):
    component_ids: list[str] = []
    weight_reduction_pct: float = Field(default=12, ge=0, le=80)
    dimension_reduction_pct: float = Field(default=8, ge=0, le=50)
    recycled_pct: float = Field(default=30, ge=0, le=100)
    carbon_factor_kgco2e_per_kg: float = Field(default=2.5, ge=0, le=20)


@app.get("/api/health")
def health(): return {"status":"ok","database":str(DB),"demo":"synthetic"}

@app.get("/api/dashboard")
def dashboard():
    m=metrics(); comps=rows("SELECT material,weight_g,product_id FROM components"); products=rows("SELECT * FROM products")
    mat={}; byproduct={}
    for x in comps:
        mat[x["material"]]=mat.get(x["material"],0)+(x["weight_g"] or 0)
        byproduct[x["product_id"]]=byproduct.get(x["product_id"],0)+(x["weight_g"] or 0)
    m["materials"]=[{"name":k,"value":round(v,1)} for k,v in mat.items()]
    m["product_readiness"]=[{"name":p["name"].replace("EcoNova ",""),"score":round(100*sum(json.loads(x["attributes"])["data_completeness"] for x in rows("SELECT attributes FROM components WHERE product_id=?",(p["id"],)))/max(1,len(rows("SELECT id FROM components WHERE product_id=?",(p["id"],)))))} for p in products]
    m["severity"]=[{"name":s,"value":sum(x["severity"]==s for x in m["findings"])} for s in ["Critical","High","Medium","Low"]]
    m["evidence_sources"]=[{"name":k,"value":v} for k,v in {x["kind"]:sum(y["kind"]==x["kind"] for y in rows("SELECT kind FROM documents")) for x in rows("SELECT DISTINCT kind FROM documents")}.items()]
    full=rows("SELECT c.material,c.weight_g,c.dimensions,c.supplier_id,c.pcr_pct,c.chemical,c.recyclable FROM components c")
    def completeness(valid): return round(100*sum(bool(valid(x)) for x in full)/max(len(full),1))
    m["attribute_completeness"]=[
        {"name":"Material","value":completeness(lambda x:x["material"])},
        {"name":"Weight","value":completeness(lambda x:x["weight_g"] is not None and x["weight_g"]>=0)},
        {"name":"Dimensions","value":completeness(lambda x:x["dimensions"])},
        {"name":"Supplier","value":completeness(lambda x:x["supplier_id"])},
        {"name":"PCR content","value":completeness(lambda x:x["pcr_pct"] is not None)},
        {"name":"Chemical disclosure","value":completeness(lambda x:x["chemical"] not in (None,"Pending","Not declared"))},
        {"name":"Recyclability evidence","value":completeness(lambda x:x["recyclable"] not in (None,"Unverified"))},
    ]
    m["formula"]="0.30 × completeness + 0.25 × evidence coverage + 0.20 × cross-source consistency + 0.15 × supplier traceability + 0.10 × assessment coverage"
    m["legal_note"]="Internal data-readiness indicator only. It is not a legal compliance determination."
    return m

@app.get("/api/products")
def products(): return rows("SELECT * FROM products")

@app.get("/api/packaging")
def packaging(search: str="", material: str="", supplier: str="", group: str="", sort: str="risk"):
    q="SELECT c.*,p.name product,p.group_name,s.name supplier,s.id supplier_code FROM components c JOIN products p ON p.id=c.product_id LEFT JOIN suppliers s ON s.id=c.supplier_id WHERE 1=1"; params=[]
    if search: q+=" AND (c.name LIKE ? OR c.id LIKE ? OR p.name LIKE ? OR s.name LIKE ?)"; params += [f"%{search}%"]*4
    if material: q+=" AND c.material=?"; params.append(material)
    if supplier: q+=" AND c.supplier_id=?"; params.append(supplier)
    if group: q+=" AND p.group_name=?"; params.append(group)
    order={"weight":"c.weight_g DESC","completeness":"json_extract(c.attributes,'$.data_completeness') ASC","risk":"CASE c.verification WHEN 'Conflict' THEN 0 WHEN 'Needs review' THEN 1 ELSE 2 END"}.get(sort,"c.id")
    q+=" ORDER BY "+order
    result=rows(q,params)
    for x in result: x["attributes"]=json.loads(x["attributes"]); x["history"]=json.loads(x["history"])
    return result

@app.get("/api/packaging/{cid}")
def packaging_detail(cid: str): return component(cid)

@app.patch("/api/packaging/{cid}")
def edit_packaging(cid: str, body: EditPayload):
    allowed={"name","material","grade","weight_g","recycled_pct","pcr_pct","dimensions","recyclable","chemical","supplier_id","verification"}
    if body.field not in allowed: raise HTTPException(400,"Unsupported attribute")
    item=component(cid); hist=item["history"]; old=item.get(body.field); hist.append({"field":body.field,"from":old,"to":body.value,"note":body.note,"at":now()})
    with connect() as c: c.execute(f"UPDATE components SET {body.field}=?, history=?, updated=? WHERE id=?",(body.value,json.dumps(hist),date.today().isoformat(),cid))
    log("Attribute updated","component",cid,f"{body.field}: {old} → {body.value}; {body.note}")
    return component(cid)

@app.get("/api/documents")
def documents():
    d=rows("SELECT * FROM documents ORDER BY uploaded DESC");
    for x in d: x["evidence_count"]=rows("SELECT count(*) n FROM evidence WHERE document_id=?",(x["id"],))[0]["n"]
    return d

@app.get("/api/documents/sample-files")
def sample_files(): return [{"name":x.name,"url":"/api/documents/sample/"+x.name,"size":x.stat().st_size} for x in sorted(SAMPLES.iterdir()) if x.is_file()]

@app.get("/api/documents/sample/{filename}")
def sample_file(filename: str):
    p=(SAMPLES/Path(filename).name).resolve()
    if not p.is_relative_to(SAMPLES.resolve()) or not p.is_file(): raise HTTPException(404,"Sample file not found")
    return FileResponse(p,filename=p.name)

def extract_document(path: Path, name: str):
    ext=path.suffix.lower(); extracted=[]; summaries=[]
    def mapped_header(header):
        h=re.sub(r"[^a-z0-9%]+"," ",str(header).lower()).strip()
        if "component id" in h or "packaging id" in h: return "packaging_id", ""
        if "product id" in h: return "product_id", ""
        if "supplier id" in h: return "supplier_id", ""
        if "supplier" in h: return "supplier", ""
        if "material" in h or "resin" in h: return "material", ""
        if "pcr" in h or "post consumer" in h: return "pcr_pct", "%"
        if "recycled" in h and ("content" in h or "%" in h): return "recycled_pct", "%"
        if "weight" in h or "mass" in h: return ("weight_g", "g") if "kg" not in h else ("weight_g", "g")
        if "dimension" in h or h in ("length mm","width mm","height mm"): return "dimensions", "mm"
        if "chemical" in h: return "chemical_disclosure", ""
        if "component" in h or "packaging" in h: return "component_name", ""
        return str(header), ""
    def mapped_value(header, value):
        attr, unit=mapped_header(header)
        if attr=="weight_g" and "kg" in str(header).lower():
            try: value=float(value)*1000
            except (TypeError,ValueError): pass
        return attr, value, unit
    if ext in (".xlsx",".xlsm"):
        from openpyxl import load_workbook
        wb=load_workbook(path,data_only=True,read_only=True)
        for ws in wb.worksheets:
            headers=[str(c.value).strip() if c.value is not None else "" for c in ws[1]]
            for row in ws.iter_rows(min_row=2):
                vals={headers[i]:cell.value for i,cell in enumerate(row) if i<len(headers) and headers[i] and cell.value is not None}
                if vals: summaries.append(f"{ws.title}: {vals}")
                for cell in row:
                    if cell.value is not None:
                        attr,value,unit=mapped_value(headers[cell.column-1] or f"Column {cell.column}",cell.value)
                        extracted.append((attr,str(value),unit,f"Sheet {ws.title} · cell {cell.coordinate}","Spreadsheet cell",.98))
    elif ext==".csv":
        with path.open(newline="",encoding="utf-8-sig") as f:
            for i,row in enumerate(csv.DictReader(f),2):
                for k,v in row.items():
                    if v:
                        attr,value,unit=mapped_value(k,v)
                        extracted.append((attr,str(value),unit,f"Row {i} · column {k}","CSV cell",.97))
    elif ext==".pdf":
        import pymupdf as fitz
        doc=fitz.open(path)
        for idx,page in enumerate(doc):
            text=page.get_text()
            summaries.append(text[:1200])
            for match in re.finditer(r"(?:material|weight|mass|PCR|recycled content|supplier|dimensions|component|chemical)[^\n]{0,90}",text,re.I):
                extracted.append((match.group(0).split(":")[0],match.group(0),"",f"Page {idx+1} · text span","PDF text",.82))
    elif ext in (".png",".jpg",".jpeg"):
        try:
            import pytesseract
            from PIL import Image
            text=pytesseract.image_to_string(Image.open(path)); summaries.append(text)
            for line in text.splitlines():
                if line.strip(): extracted.append(("OCR text",line.strip(),"","Image page","OCR",.65))
        except Exception: raise ValueError("OCR is unavailable for this image. Install Tesseract and pytesseract, or upload a text-based specification.")
    else: raise ValueError("Unsupported file type. Upload XLSX, CSV, PDF, PNG, or JPG.")
    return extracted, " · ".join(s for s in summaries if s)[:900]


def validate_upload(filename: str, size: int=0):
    allowed={".xlsx",".xlsm",".csv",".pdf",".png",".jpg",".jpeg"}
    ext=Path(filename or "").suffix.lower()
    if ext not in allowed: raise HTTPException(400,"Unsupported file type. Upload XLSX, CSV, PDF, PNG, or JPG.")
    if size>12*1024*1024: raise HTTPException(413,"File exceeds 12 MB limit")
    return ext

@app.post("/api/documents/upload")
async def upload_document(file: UploadFile=File(...)):
    ext=validate_upload(file.filename or "")
    raw=await file.read(12*1024*1024+1)
    validate_upload(file.filename or "",len(raw))
    name=re.sub(r"[^A-Za-z0-9._ -]","_",Path(file.filename or "upload").name)[:120]; dest=UPLOADS/(uuid.uuid4().hex+ext); dest.write_bytes(raw)
    try: extracted,summary=extract_document(dest,name)
    except Exception as e: dest.unlink(missing_ok=True); raise HTTPException(422,str(e))
    did="DOC-"+uuid.uuid4().hex[:8].upper()
    kind="Spreadsheet" if ext in (".xlsx",".xlsm",".csv") else "PDF" if ext==".pdf" else "Image"
    with connect() as c:
        c.execute("INSERT INTO documents VALUES(?,?,?,?,?,?,?)",(did,name,kind,"Processed",now(),len(raw),summary or f"Processed {len(extracted)} evidence cells."))
        for attr,value,unit,loc,method,confidence in extracted[:1000]:
            c.execute("INSERT INTO evidence VALUES(?,?,?,?,?,?,?,?,?,?,?)",(str(uuid.uuid4()),"",attr,value,unit,did,name,loc,method,confidence,"Needs review"))
    log("Document uploaded and extracted","document",did,f"{name}: {len(extracted)} extracted values")
    return {"id":did,"name":name,"status":"Processed","kind":kind,"extracted_count":len(extracted),"summary":summary,"evidence":rows("SELECT * FROM evidence WHERE document_id=?",(did,))[:100]}

@app.post("/api/documents/{did}/process")
def process_document(did: str):
    doc=rows("SELECT * FROM documents WHERE id=?",(did,))
    if not doc: raise HTTPException(404,"Document not found")
    return {"id":did,"status":doc[0]["status"],"summary":doc[0]["summary"],"evidence":rows("SELECT * FROM evidence WHERE document_id=?",(did,))}

@app.get("/api/documents/{did}/evidence")
def document_evidence(did: str): return rows("SELECT * FROM evidence WHERE document_id=?",(did,))

@app.post("/api/reconciliation/run")
def reconcile(): return {"created":0,"conflicts":rows("SELECT * FROM conflicts"),"message":"Seed conflicts are normalized and ready for human review."}

@app.get("/api/conflicts")
def conflicts(): return rows("SELECT c.*,p.name product FROM conflicts c LEFT JOIN components x ON x.id=c.component_id LEFT JOIN products p ON p.id=x.product_id ORDER BY CASE severity WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END")

@app.post("/api/conflicts/{cid}/resolve")
def resolve_conflict(cid: str, body: ResolvePayload):
    cf=rows("SELECT * FROM conflicts WHERE id=?",(cid,))
    if not cf: raise HTTPException(404,"Conflict not found")
    x=cf[0]; value=body.value or x["value_a"]
    fields={"material":"material","weight_g":"weight_g","pcr_pct":"pcr_pct","chemical":"chemical"}
    if x["attribute"] in fields and body.status in ("Resolved","Accepted with justification"):
        field=fields[x["attribute"]]
        if field=="weight_g":
            n=re.search(r"[0-9.]+",value)
            value=float(n.group())*(1000 if "kg" in value.lower() else 1) if n else value
        old=component(x["component_id"]).get(field)
        if str(old)!=str(value): edit_packaging(x["component_id"],EditPayload(field=field,value=value,note=body.note or "Conflict resolution"))
    status=body.status if body.status in ("Resolved","Accepted with justification","Under review") else "Resolved"
    with connect() as c: c.execute("UPDATE conflicts SET status=?,resolution=?,note=?,updated=? WHERE id=?",(status,str(value),body.note,now(),cid))
    log("Conflict resolved","conflict",cid,f"{status}: {value}; {body.note}")
    return {"conflict":rows("SELECT * FROM conflicts WHERE id=?",(cid,))[0],"dashboard":dashboard()}

@app.post("/api/assessment/run")
def assessment_run():
    # Deterministic screening: evidence gaps remain findings; no legal pass/fail assertion.
    return {"findings":rows("SELECT * FROM findings ORDER BY CASE severity WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END"),"readiness":metrics()["score"],"note":"Simplified POC screening only. Market-specific legal interpretation and evidence review are required."}

@app.get("/api/assessment/findings")
def findings(severity: str="", area: str=""):
    q="SELECT f.*,c.name component,c.product_id FROM findings f JOIN components c ON c.id=f.component_id WHERE 1=1"; p=[]
    if severity: q+=" AND f.severity=?"; p.append(severity)
    if area: q+=" AND f.area=?"; p.append(area)
    q += " ORDER BY CASE f.severity WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END"
    return rows(q,p)

@app.post("/api/findings/{fid}/review")
def review_finding(fid: str, body: ReviewPayload):
    with connect() as c:
        cur=c.execute("UPDATE findings SET reviewed=? WHERE id=?",(body.reviewed,fid))
        if cur.rowcount==0: raise HTTPException(404,"Finding not found")
    log("Finding review updated","finding",fid,f"{body.reviewed}: {body.note}")
    return {"finding":rows("SELECT * FROM findings WHERE id=?",(fid,))[0],"dashboard":dashboard()}

@app.post("/api/optimization/simulate")
def simulate(body: SimPayload):
    comps=rows("SELECT * FROM components"+(" WHERE id IN ("+",".join("?" for _ in body.component_ids)+")" if body.component_ids else ""),body.component_ids)
    if not comps: raise HTTPException(404,"No packaging components selected")
    before=sum(x["weight_g"] or 0 for x in comps); after=before*(1-body.weight_reduction_pct/100)
    volume_before=sum(math.prod(float(z.strip()) for z in re.findall(r"[0-9.]+",x["dimensions"])[:3]) if len(re.findall(r"[0-9.]+",x["dimensions"]))>=3 else 0 for x in comps)
    volume_after=volume_before*(1-body.dimension_reduction_pct/100)
    avoided_kg=(before-after)/1000; carbon=avoided_kg*body.carbon_factor_kgco2e_per_kg
    result={"component_count":len(comps),"before_weight_g":round(before,1),"after_weight_g":round(after,1),"savings_g":round(before-after,1),"reduction_pct":body.weight_reduction_pct,"before_volume_cm3":round(volume_before/1000,1),"after_volume_cm3":round(volume_after/1000,1),"volume_reduction_pct":body.dimension_reduction_pct,"estimated_carbon_kgco2e":round(carbon,3),"carbon_factor":body.carbon_factor_kgco2e_per_kg,"recycled_content_pct":body.recycled_pct,"assumptions":["Linear mass and volume change entered by user; no material-specific redesign model.","Carbon estimate uses user-configurable factor and excludes manufacturing, transport, and end-of-life details.","Any reduction requires packaging protection and transport validation."]}
    sid="SIM-"+uuid.uuid4().hex[:8].upper()
    with connect() as c: c.execute("INSERT INTO scenarios VALUES(?,?,?,?,?)",(sid,"Interactive scenario",json.dumps(body.model_dump()),json.dumps(result),now()))
    return {"id":sid,**result}

@app.get("/api/suppliers")
def suppliers():
    data=rows("SELECT * FROM suppliers")
    for s in data:
        s["components"]=rows("SELECT id,name,material,verification FROM components WHERE supplier_id=?",(s["id"],)); s["component_count"]=len(s["components"]); s["evidence_count"]=rows("SELECT count(*) n FROM evidence WHERE component_id IN (SELECT id FROM components WHERE supplier_id=?)",(s["id"],))[0]["n"]; s["coverage"]=round(100*s["evidence_count"]/max(1,4*s["component_count"]))
    return data

@app.post("/api/suppliers/{sid}/request")
def supplier_request(sid: str):
    s=rows("SELECT * FROM suppliers WHERE id=?",(sid,))
    if not s: raise HTTPException(404,"Supplier not found")
    log("Supplier information request drafted","supplier",sid,"Draft request prepared for owner review.")
    return {"supplier":s[0],"draft":f"Please provide current material composition, recycled-content evidence, chemical disclosure, and end-of-life information for the packaging components supplied to EcoNova Consumer Electronics. This is a draft request; review and send through your approved process."}

@app.get("/api/roadmap")
def roadmap(): return rows("SELECT * FROM roadmap ORDER BY year,due")

class RoadmapUpdate(BaseModel):
    status: str | None = None
    due: str | None = None
    department: str | None = None

@app.post("/api/roadmap/{tid}/update")
def update_task(tid: str, body: RoadmapUpdate):
    task=rows("SELECT * FROM roadmap WHERE id=?",(tid,))
    if not task: raise HTTPException(404,"Task not found")
    for key,val in body.model_dump(exclude_none=True).items():
        if key=="status" and val not in ("Open","In progress","Complete"): raise HTTPException(400,"Invalid status")
        with connect() as c: c.execute(f"UPDATE roadmap SET {key}=? WHERE id=?",(val,tid))
    log("Roadmap task updated","roadmap",tid,json.dumps(body.model_dump(exclude_none=True)))
    return rows("SELECT * FROM roadmap WHERE id=?",(tid,))[0]

def report_data(pid):
    p=rows("SELECT * FROM products WHERE id=?",(pid,))
    if not p: raise HTTPException(404,"Product not found")
    comps=rows("SELECT * FROM components WHERE product_id=?",(pid,))
    for x in comps:
        x["attributes"]=json.loads(x["attributes"]); x["evidence"]=rows("SELECT filename,location,attribute,value,unit,review FROM evidence WHERE component_id=?",(x["id"],)); x["findings"]=rows("SELECT id,title,severity,result,reviewed FROM findings WHERE component_id=?",(x["id"],))
    return {"report_type":"POC Packaging Data Readiness Report","assessment_date":date.today().isoformat(),"product":p[0],"readiness":metrics()["score"],"legal_status":"Not determined","components":comps,"findings":[f for x in comps for f in x["findings"]],"assumptions":["Synthetic demonstration dataset.","Internal readiness indicator is not a legal compliance determination.","Regulatory screening criteria are simplified and require expert validation."]}

@app.get("/api/reports/{pid}/json")
def report_json(pid: str): return report_data(pid)

@app.get("/api/reports/{pid}/csv")
def report_csv(pid: str):
    data=report_data(pid); out=io.StringIO(); writer=csv.writer(out); writer.writerow(["Product ID","Product","Component ID","Component","Level","Material","Weight g","Recycled %","PCR %","Supplier","Verification","Evidence refs"])
    for c in data["components"]: writer.writerow([data["product"]["id"],data["product"]["name"],c["id"],c["name"],c["level"],c["material"],c["weight_g"],c["recycled_pct"],c["pcr_pct"],c["supplier_id"],c["verification"],"; ".join(e["filename"]+" / "+e["location"] for e in c["evidence"])])
    return Response(out.getvalue(),media_type="text/csv",headers={"Content-Disposition":f"attachment; filename=packtrace-{pid}.csv"})

@app.get("/api/reports/{pid}/pdf")
def report_pdf(pid: str):
    data=report_data(pid)
    import pymupdf as fitz
    doc=fitz.open(); page=doc.new_page(width=595,height=842); y=58
    page.insert_text((44,y),"PackTrace AI",fontsize=24,color=(.08,.32,.24)); y+=32
    page.insert_text((44,y),"POC Packaging Data Readiness Report",fontsize=14); y+=26
    p=data["product"]; page.insert_text((44,y),f"{p['name']} · {p['id']} · Assessment date {data['assessment_date']}",fontsize=10); y+=24
    page.insert_text((44,y),f"Readiness indicator: {data['readiness']}/100   Legal status: Not determined",fontsize=11); y+=28
    page.insert_text((44,y),"Packaging hierarchy",fontsize=13,color=(.08,.32,.24)); y+=20
    for c in data["components"]:
        txt=f"{c['id']}  {c['name']} | {c['material']} · {c['weight_g']} g · Recycled {c['recycled_pct']}% · {c['verification']}"
        page.insert_textbox(fitz.Rect(44,y,550,y+28),txt,fontsize=9); y+=31
        if y>735: page=doc.new_page(width=595,height=842); y=55
    y+=12; page.insert_text((44,y),"Assessment findings",fontsize=13,color=(.08,.32,.24)); y+=20
    for f in data["findings"][:16]:
        page.insert_textbox(fitz.Rect(44,y,550,y+34),f"[{f['severity']}] {f['title']} — {f['result']}",fontsize=8); y+=36
        if y>735: page=doc.new_page(width=595,height=842); y=55
    y+=15
    for line in data["assumptions"]:
        page.insert_textbox(fitz.Rect(44,y,550,y+24),"• "+line,fontsize=8); y+=23
    return Response(doc.tobytes(),media_type="application/pdf",headers={"Content-Disposition":f"attachment; filename=packtrace-{pid}-readiness.pdf"})

@app.get("/api/audit")
def audit(): return rows("SELECT * FROM audit ORDER BY id DESC LIMIT 80")

@app.get("/api/demo/steps")
def demo_steps(): return [{"title":t,"description":d,"view":v} for t,d,v in [("Executive overview","A transparent readiness baseline across 15 packaging components.","dashboard"),("Explore components","Inspect a PET protective tray and its source-backed attributes.","inventory"),("Trace the evidence","Open supplier and ERP evidence with source locations.","documents"),("Review a conflict","Compare ERP resin description with the supplier certificate.","conflicts"),("Assess an evidence gap","Review missing recyclability and chemical evidence.","assessment"),("Resolve with a reviewer","Record a verified value and watch the readiness calculation update.","conflicts"),("Model an optimization","Adjust mass and dimensions with visible assumptions.","simulator"),("See the impact","Compare packaging mass and an illustrative carbon estimate.","simulator"),("Plan the work","See internal milestones through 2030.","roadmap"),("Export the report","Download a POC readiness report for the selected product.","reports")]]

@app.get("/")
def index(): return FileResponse(ROOT/"frontend"/"index.html")

app.mount("/static",StaticFiles(directory=ROOT/"frontend"),name="static")
init_db()
