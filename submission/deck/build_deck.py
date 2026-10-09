"""Fill the AI Builder Cup submission template with the Provenance deck.

    python submission/deck/build_deck.py --template <Submission_Template.pptx> \\
        --leader "Full Name" [--video URL] [-o Provenance_Deck.pptx]

The template's own frame (header art, footer, fonts, closing slide) is kept as is; only its text
boxes are replaced. Diagrams are native shapes so they stay editable in Google Slides. Numbers come
from numbers.json, words from content.py. Standard library only.

The template file is Hack2skill's and is not committed; pass its path.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import content as C

HERE = Path(__file__).parent
EMU = 914400
FONT, SEMI, MED = "Google Sans Flex", "Google Sans Flex SemiBold", "Google Sans Flex Medium"

INK, MUTED, LINE, CARD, WHITE = "202124", "5F6368", "DADCE0", "F1F3F4", "FFFFFF"
BLUE, BLUE_T = "1A73E8", "E8F0FE"
GREEN, GREEN_T = "188038", "E6F4EA"
AMBER, AMBER_T = "B06000", "FEF7E0"
RED, RED_T = "C5221F", "FCE8E6"
TONES = {"green": (GREEN, GREEN_T), "amber": (AMBER, AMBER_T), "blue": (BLUE, BLUE_T), "red": (RED, RED_T)}

REPO = "https://github.com/iqbalnit/provenance"
APP = "https://ai-builder-cup-2579.web.app"

# Template slide numbers in final order. 2 (the "please download" note) and 7 (optional
# wireframes) are dropped; the blank 15 becomes the reversal slide after Features.
ORDER = [1, 3, 4, 5, 15, 6, 8, 9, 10, 11, 12, 13, 14, 16]


def emu(v: float) -> int:
    return int(round(v * EMU))


# ---------------------------------------------------------------- DrawingML helpers

class Slide:
    """Collects shapes for one slide; ids start high to stay clear of the template's."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.images: list[tuple[str, Path]] = []  # (rId, source)
        self._id = 1000

    def nid(self) -> int:
        self._id += 1
        return self._id

    def add(self, xml: str) -> None:
        self.parts.append(xml)


def runs(text: str, sz: float, color: str = INK, face: str = FONT) -> str:
    """`**bold**` markup -> runs."""
    out = []
    for i, chunk in enumerate(re.split(r"\*\*", text)):
        if not chunk:
            continue
        b = ' b="1"' if i % 2 else ""  # inline bold: same face, bold flag, so any fallback font stays bold
        f = face
        out.append(f'<a:r><a:rPr lang="en-GB" sz="{int(sz * 100)}"{b} dirty="0"><a:solidFill><a:srgbClr val="{color}"/>'
                   f'</a:solidFill><a:latin typeface="{f}"/><a:ea typeface="{f}"/><a:cs typeface="{f}"/>'
                   f'<a:sym typeface="{f}"/></a:rPr><a:t xml:space="preserve">{escape(chunk)}</a:t></a:r>')
    return "".join(out)


def para(text: str = "", sz: float = 12, color: str = INK, face: str = FONT, align: str = "l",
         bullet: bool = False, after: float = 0, line: float | None = None) -> str:
    ln = f'<a:lnSpc><a:spcPct val="{int(line * 100000)}"/></a:lnSpc>' if line else ""
    if bullet:
        ppr = (f'<a:pPr marL="{emu(0.17)}" indent="{-emu(0.17)}" algn="{align}">{ln}<a:spcBef><a:spcPts val="0"/></a:spcBef>'
               f'<a:spcAft><a:spcPts val="{int(after * 100)}"/></a:spcAft><a:buClr><a:srgbClr val="{color}"/></a:buClr>'
               f'<a:buSzPct val="100000"/><a:buFont typeface="Arial"/><a:buChar char="&#8226;"/></a:pPr>')
    else:
        ppr = (f'<a:pPr marL="0" indent="0" algn="{align}">{ln}<a:spcBef><a:spcPts val="0"/></a:spcBef>'
               f'<a:spcAft><a:spcPts val="{int(after * 100)}"/></a:spcAft><a:buNone/></a:pPr>')
    body = runs(text, sz, color, face) if text else ""
    return f'<a:p>{ppr}{body}<a:endParaRPr lang="en-GB" sz="{int(sz * 100)}" dirty="0"/></a:p>'


def box(s: Slide, x, y, w, h, paras: str | list[str] = "", fill: str | None = None, line: str | None = None,
        geom: str = "rect", anchor: str = "t", inset: float = 0.08, line_w: float = 0.75, name: str = "",
        radius: float = 0.08) -> None:
    if isinstance(paras, list):
        paras = "".join(paras)
    i = s.nid()
    tx = ' txBox="1"' if not fill and not line else ""
    av = f'<a:gd name="adj" fmla="val {int(radius * 100000)}"/>' if geom == "roundRect" else ""
    fill_x = f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>' if fill else "<a:noFill/>"
    line_x = (f'<a:ln w="{int(line_w * 12700)}"><a:solidFill><a:srgbClr val="{line}"/></a:solidFill></a:ln>'
              if line else "<a:ln><a:noFill/></a:ln>")
    ins = emu(inset)
    s.add(f'<p:sp><p:nvSpPr><p:cNvPr id="{i}" name="{escape(name or f"Shape {i}")}"/><p:cNvSpPr{tx}/><p:nvPr/></p:nvSpPr>'
          f'<p:spPr><a:xfrm><a:off x="{emu(x)}" y="{emu(y)}"/><a:ext cx="{emu(w)}" cy="{emu(h)}"/></a:xfrm>'
          f'<a:prstGeom prst="{geom}"><a:avLst>{av}</a:avLst></a:prstGeom>{fill_x}{line_x}</p:spPr>'
          f'<p:txBody><a:bodyPr wrap="square" lIns="{ins}" tIns="{ins}" rIns="{ins}" bIns="{ins}" anchor="{anchor}" rtlCol="0">'
          f'<a:noAutofit/></a:bodyPr><a:lstStyle/>{paras or para()}</p:txBody></p:sp>')


def arrow(s: Slide, x1, y1, x2, y2, color: str = MUTED, w: float = 1.25, head: bool = True, dash: bool = False) -> None:
    i = s.nid()
    flip = (' flipH="1"' if x2 < x1 else "") + (' flipV="1"' if y2 < y1 else "")
    d = '<a:prstDash val="dash"/>' if dash else ""
    tail = '<a:tailEnd type="triangle" w="med" len="med"/>' if head else ""
    s.add(f'<p:cxnSp><p:nvCxnSpPr><p:cNvPr id="{i}" name="Arrow {i}"/><p:cNvCxnSpPr/><p:nvPr/></p:nvCxnSpPr>'
          f'<p:spPr><a:xfrm{flip}><a:off x="{emu(min(x1, x2))}" y="{emu(min(y1, y2))}"/>'
          f'<a:ext cx="{emu(abs(x2 - x1))}" cy="{emu(abs(y2 - y1))}"/></a:xfrm>'
          f'<a:prstGeom prst="straightConnector1"><a:avLst/></a:prstGeom>'
          f'<a:ln w="{int(w * 12700)}"><a:solidFill><a:srgbClr val="{color}"/></a:solidFill>{d}{tail}</a:ln></p:spPr></p:cxnSp>')


def picture(s: Slide, src: Path, x, y, w, h, descr: str) -> None:
    rid = f"rIdP{len(s.images) + 1}"
    s.images.append((rid, src))
    i = s.nid()
    s.add(f'<p:pic><p:nvPicPr><p:cNvPr id="{i}" name="Picture {i}" descr="{escape(descr)}"/>'
          f'<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr>'
          f'<p:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
          f'<p:spPr><a:xfrm><a:off x="{emu(x)}" y="{emu(y)}"/><a:ext cx="{emu(w)}" cy="{emu(h)}"/></a:xfrm>'
          f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
          f'<a:ln w="9525"><a:solidFill><a:srgbClr val="{LINE}"/></a:solidFill></a:ln></p:spPr></p:pic>')


def table(s: Slide, x, y, col_w: list[float], rows: list[list[str]], row_h: float = 0.3, sz: float = 10,
          header_fill: str = INK, tones: dict[tuple[int, int], str] | None = None) -> None:
    tones = tones or {}
    i = s.nid()
    grid = "".join(f'<a:gridCol w="{emu(c)}"/>' for c in col_w)
    none = "<a:noFill/>"

    def cell(text: str, r: int, c: int) -> str:
        head = r == 0
        color = WHITE if head else tones.get((r, c), INK)
        face = SEMI if head or c == 0 else FONT
        p = para(text, sz=sz, color=color, face=face, align="l" if c <= 1 else "ctr")
        bottom = f'<a:lnB w="9525"><a:solidFill><a:srgbClr val="{LINE}"/></a:solidFill></a:lnB>'
        fill = f'<a:solidFill><a:srgbClr val="{header_fill}"/></a:solidFill>' if head else none
        m = emu(0.06)
        return (f'<a:tc><a:txBody><a:bodyPr/><a:lstStyle/>{p}</a:txBody>'
                f'<a:tcPr marL="{m}" marR="{m}" marT="{emu(0.03)}" marB="{emu(0.03)}" anchor="ctr">'
                f'<a:lnL><a:noFill/></a:lnL><a:lnR><a:noFill/></a:lnR><a:lnT><a:noFill/></a:lnT>{bottom}{fill}</a:tcPr></a:tc>')

    trs = "".join(f'<a:tr h="{emu(row_h)}">' + "".join(cell(t, r, c) for c, t in enumerate(row)) + "</a:tr>"
                  for r, row in enumerate(rows))
    s.add(f'<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="{i}" name="Table {i}"/>'
          f'<p:cNvGraphicFramePr><a:graphicFrameLocks noGrp="1"/></p:cNvGraphicFramePr><p:nvPr/></p:nvGraphicFramePr>'
          f'<p:xfrm><a:off x="{emu(x)}" y="{emu(y)}"/><a:ext cx="{emu(sum(col_w))}" cy="{emu(row_h * len(rows))}"/></p:xfrm>'
          f'<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table">'
          f'<a:tbl><a:tblPr firstRow="1"/><a:tblGrid>{grid}</a:tblGrid>{trs}</a:tbl></a:graphicData></a:graphic></p:graphicFrame>')


# ---------------------------------------------------------------- shared slide furniture

LEFT, RIGHT = 0.4, 9.6
WIDTH = RIGHT - LEFT
TOP = 1.45  # content starts below kicker + headline
BOTTOM = 5.3  # above the template footer


def heading(s: Slide, kicker: str, headline: str) -> None:
    """The template's own heading (16 pt Medium, kept verbatim) plus our one-line message."""
    box(s, LEFT - 0.08, 0.68, WIDTH + 0.16, 0.34, para(kicker, 16, INK, MED), inset=0.08)
    box(s, LEFT - 0.08, 0.98, WIDTH + 0.16, 0.42, para(headline, 13, MUTED), inset=0.08)


def card(s: Slide, x, y, w, h, title: str, body: str | list[str], tone: str | None = None,
         title_sz: float = 12, body_sz: float = 10.5, bullets: bool = False) -> None:
    edge, fill = TONES[tone] if tone else (LINE, CARD)
    ps = [para(title, title_sz, edge if tone else INK, SEMI, after=4)]
    items = body if isinstance(body, list) else [body]
    ps += [para(t, body_sz, INK, bullet=bullets, after=4, line=1.05) for t in items]
    box(s, x, y, w, h, ps, fill=fill, geom="roundRect", inset=0.12, radius=0.06, name=title)


def node(s: Slide, x, y, w, h, title: str, sub: str = "", tone: str | None = None, sz: float = 10.5) -> None:
    edge, fill = TONES[tone] if tone else (LINE, WHITE)
    ps = [para(title, sz, INK, SEMI, align="ctr")]
    if sub:
        ps.append(para(sub, sz - 2, MUTED, align="ctr"))
    box(s, x, y, w, h, ps, fill=fill, line=edge, geom="roundRect", anchor="ctr", inset=0.05, radius=0.15, name=title)


def fmt_pct(v) -> str:
    if v is None:
        return "running"
    p = v * 100
    return f"{p:.0f}%" if abs(p - round(p)) < 0.05 else f"{p:.1f}%"


# ---------------------------------------------------------------- slides

def s_team(s: Slide, leader: str) -> None:
    ps = [para("Team Details", 21, INK, SEMI, after=6),
          para(f"**Team name:** {C.TEAM_NAME}", 15, after=3),
          para(f"**Team leader name:** {leader}", 15, after=3),
          para(f"**Problem statement:** {C.PROBLEM}", 15, line=1.05)]
    box(s, 0.16, 3.0, 9.6, 2.0, ps, inset=0.1)


def s_idea(s: Slide, n: dict) -> None:
    heading(s, "Brief about the idea", C.IDEA_HEADLINE)
    box(s, LEFT - 0.08, TOP + 0.05, 5.6, 3.8, [para(t, 11.5, after=9, line=1.08) for t in C.IDEA_BODY])
    re_ = n["rule_engine"]
    stats = [
        (f"{re_['alerts']:,}", f"alerts from {re_['transactions'] / 1e6:.1f}M transactions: our own rule engine on the SAML-D dataset", None),
        (f"{re_['fp_rate'] * 100:.1f}%", "of those alerts are false positives (SAML-D labels)", None),
        ("100%", "of sentences Provenance emits cite a ledger claim, enforced by a parser", "blue"),
    ]
    y = TOP + 0.05
    for big, small, tone in stats:
        color = BLUE if tone else INK
        box(s, 6.0, y, 3.6, 1.15, [para(big, 26, color, SEMI), para(small, 9.5, MUTED, line=1.05)],
            fill=CARD, geom="roundRect", inset=0.12, radius=0.06)
        y += 1.27


def s_opps(s: Slide) -> None:
    heading(s, "Opportunities", C.OPPORTUNITIES_HEADLINE)
    w, gap = (WIDTH - 2 * 0.25) / 3, 0.25
    for k, (title, items) in enumerate(C.OPPORTUNITIES):
        card(s, LEFT + k * (w + gap), TOP + 0.05, w, 3.1, title, items, tone="blue" if k == 2 else None,
             title_sz=13, body_sz=10.5, bullets=True)


def s_features(s: Slide) -> None:
    heading(s, "List of features offered by the solution", C.FEATURES_HEADLINE)
    cols, gap = 3, 0.22
    w, h = (WIDTH - (cols - 1) * gap) / cols, 1.5
    for k, (title, body) in enumerate(C.FEATURES):
        x, y = LEFT + (k % cols) * (w + gap), TOP + 0.05 + (k // cols) * (h + gap)
        box(s, x, y, w, h, fill=CARD, geom="roundRect", radius=0.06)
        box(s, x + 0.14, y + 0.15, 0.36, 0.36, para(str(k + 1), 12, WHITE, SEMI, align="ctr"),
            fill=BLUE, geom="ellipse", anchor="ctr", inset=0)
        box(s, x + 0.58, y + 0.1, w - 0.68, 0.45, para(title, 12, INK, SEMI), anchor="ctr", inset=0.02)
        box(s, x + 0.1, y + 0.6, w - 0.2, h - 0.65, para(body, 10, INK, line=1.05), inset=0.04)
    box(s, LEFT - 0.08, TOP + 0.05 + 2 * h + gap + 0.08, WIDTH + 0.16, 0.35, para(C.FEATURES_FOOTER, 10, MUTED))


def s_reversal(s: Slide, n: dict) -> None:
    heading(s, "Innovation: the staleness reversal", C.REVERSAL_HEADLINE)
    w, gap, y, h = (WIDTH - 2 * 0.3) / 3, 0.3, TOP + 0.05, 1.75
    for k, (label, verdict, why, tone) in enumerate(C.REVERSAL_TILES):
        x = LEFT + k * (w + gap)
        edge, fill = TONES[tone]
        box(s, x, y, w, h, [para(label, 10, MUTED, after=4), para(verdict, 20, edge, SEMI, after=4),
                            para(why, 10, INK, line=1.05)],
            fill=fill, line=edge if k == 0 else None, line_w=1.5, geom="roundRect", inset=0.14, radius=0.06)
        if k < 2:
            arrow(s, x + w + 0.03, y + h / 2, x + w + gap - 0.03, y + h / 2, MUTED, 1.5)
    box(s, LEFT - 0.08, y + h + 0.05, WIDTH, 0.3, para(C.REVERSAL_CAPTION, 9.5, MUTED))
    hero = n["hero"]
    real = [para("On real data", 12, INK, SEMI, after=4),
            para(f"A real person designated by OFAC after our archived list (SDN {hero['sdn']}) sits on a SAML-D "
                 f"structuring alert. The {hero['archived_as_of']} list says **no match**; the {hero['live_as_of']} "
                 f"list says **match**. Each claim stores both dates, so the gate can tell which list it is reading.",
                 10.5, line=1.05)]
    box(s, LEFT, y + h + 0.42, WIDTH, 1.2, real, fill=CARD, geom="roundRect", inset=0.14, radius=0.06)


def s_flow(s: Slide) -> None:
    heading(s, "Process flow diagram or Use-case diagram",
            "One alert through the agent graph: evidence first, words second, code decides")
    y1, h = TOP + 0.2, 0.62
    node(s, 0.4, y1, 1.15, h, "Alert", "rule hit")
    node(s, 1.85, y1, 1.35, h, "Typologist", "name-blind", "blue")
    node(s, 3.5, y1, 1.35, h, "Evidence planner", "per typology")
    arrow(s, 1.55, y1 + h / 2, 1.85, y1 + h / 2)
    arrow(s, 3.2, y1 + h / 2, 3.5, y1 + h / 2)
    # parallel agents
    px, pw = 5.15, 2.55
    box(s, px, y1 - 0.25, pw, 2.0, para("Parallel evidence agents", 9, MUTED, align="ctr"),
        line=LINE, geom="roundRect", radius=0.05, inset=0.04)
    agents = [("Transactions", "BigQuery templates"), ("KYC", "customer profile"),
              ("Watchlist", "OFAC SDN, dated"), ("Adverse media", "Search + guard")]
    for k, (t, sub) in enumerate(agents):
        node(s, px + 0.15, y1 + k * 0.42, pw - 0.3, 0.36, f"{t} · {sub}", sz=9.5)
    arrow(s, 4.85, y1 + h / 2, px, y1 + h / 2)
    node(s, 8.0, y1 + 0.35, 1.6, 0.9, "Claim ledger", "Firestore, two timestamps", "blue")
    arrow(s, px + pw, y1 + 0.8, 8.0, y1 + 0.8)
    # second row, right to left
    y2 = 3.75
    node(s, 7.7, y2, 1.9, 0.75, "Disposition draft", "Gemini, must cite")
    node(s, 5.3, y2, 1.9, 0.75, "Citation verifier", "parser; ≤ 3 drafts", "red")
    node(s, 2.9, y2, 1.9, 0.75, "Policy gate", "six conditions", "blue")
    arrow(s, 8.8, y1 + 1.25, 8.65, y2)
    arrow(s, 7.7, y2 + 0.28, 7.2, y2 + 0.28)
    arrow(s, 7.2, y2 + 0.5, 7.7, y2 + 0.5, RED, dash=True)
    box(s, 6.95, y2 + 0.78, 1.6, 0.3, para("rejected: redraft", 8.5, RED, align="ctr"), inset=0)
    arrow(s, 5.3, y2 + 0.38, 4.8, y2 + 0.38)
    node(s, 0.4, y2 - 0.42, 2.1, 0.62, "Auto-close", "all six pass", "green")
    node(s, 0.4, y2 + 0.5, 2.1, 0.62, "Escalate to analyst", "case file + SAR draft", "amber")
    arrow(s, 2.9, y2 + 0.3, 2.5, y2 - 0.1)
    arrow(s, 2.9, y2 + 0.45, 2.5, y2 + 0.8)
    box(s, 0.35, y2 + 1.18, 4.6, 0.3, para("Nightly sweep: re-checks auto-closed cases against the newest lists and reopens what changed.",
                                         8.5, MUTED, line=1.0), inset=0.02)


def s_arch(s: Slide) -> None:
    heading(s, "Architecture diagram of the proposed solution",
            "Serverless on Google Cloud: Firebase in front, one Cloud Run service, managed data behind it")
    y = TOP + 0.25
    node(s, 0.4, y + 1.05, 1.3, 0.75, "Analyst", "browser")
    node(s, 2.0, y + 1.05, 1.55, 0.75, "Firebase Hosting", "console, /api rewrite", "blue")
    arrow(s, 1.7, y + 1.42, 2.0, y + 1.42)
    cx, cw, ch = 3.85, 2.45, 2.85
    box(s, cx, y, cw, ch, [para("Cloud Run", 13, BLUE, SEMI, align="ctr", after=6),
                          para("FastAPI service", 10, INK, align="ctr", after=2),
                          para("ADK agent graph", 10, INK, align="ctr", after=2),
                          para("verifier · gate · staleness", 10, INK, align="ctr", after=2),
                          para("deterministic Python", 9, MUTED, align="ctr")],
        fill=BLUE_T, line=BLUE, line_w=1.5, geom="roundRect", anchor="ctr", radius=0.06)
    arrow(s, 3.55, y + 1.42, cx, y + 1.42)
    deps = [("Gemini on Vertex AI", "agents + Search grounding", "blue"),
            ("Firestore", "claim ledger, cases, reviews", None),
            ("BigQuery", "transactions, alerts, eval", None),
            ("Cloud Storage", "OFAC lists, KYC", None),
            ("Secret Manager · Scheduler", "keys · nightly sweep", None),
            ("Model Armor", "web-content screening (adapter)", None)]
    dx, dw, dh, gap = 6.95, 2.65, 0.42, 0.065
    for k, (t, sub, tone) in enumerate(deps):
        yy = y - 0.05 + k * (dh + gap)
        node(s, dx, yy, dw, dh, f"{t}", sub, tone, sz=9.5)
        arrow(s, cx + cw, y + ch / 2, dx, yy + dh / 2, LINE if tone is None else BLUE, 1.0, head=False)
    box(s, 0.32, y + 2.15, 3.4, 0.75, para("One public URL; scales to zero when idle. Every case, claim and "
                                           "review is in Firestore for audit.", 9.5, MUTED, line=1.05))


def s_tech(s: Slide) -> None:
    heading(s, "Technologies to be used in the solution", "Google Cloud end to end, with the trust logic in plain Python")
    groups = [
        ("Models", ["Gemini on Vertex AI", "Google Search grounding", "structured JSON output"]),
        ("Agents", ["Agent Development Kit (ADK)", "Sequential · Parallel · Loop agents", "function tools"]),
        ("Serving", ["Cloud Run", "FastAPI", "Firebase Hosting", "Secret Manager", "Cloud Scheduler"]),
        ("Data", ["Firestore", "BigQuery", "Cloud Storage", "OFAC SDN (dated snapshots)", "SAML-D"]),
        ("Trust and eval", ["citation verifier", "policy gate", "staleness auditor", "injection guard", "five-arm eval, ECE"]),
    ]
    y = TOP + 0.1
    for label, chips in groups:
        box(s, LEFT - 0.05, y, 1.45, 0.5, para(label, 12, INK, SEMI), anchor="ctr", inset=0.02)
        x = 1.95
        for c in chips:
            w = 0.25 + 0.075 * len(c)
            tone = BLUE_T if label in ("Models", "Serving", "Data") and k_google(c) else CARD
            box(s, x, y + 0.07, w, 0.36, para(c, 10, INK, align="ctr"), fill=tone, geom="roundRect",
                anchor="ctr", inset=0.02, radius=0.5)
            x += w + 0.12
        y += 0.68
    box(s, LEFT - 0.08, y, WIDTH, 0.3, para("Blue: Google Cloud services in the deployed prototype.", 9, MUTED))


def k_google(name: str) -> bool:
    return any(k in name for k in ("Gemini", "Google", "Cloud", "Firebase", "Firestore", "BigQuery", "Secret"))


def s_cost(s: Slide, n: dict) -> None:
    heading(s, "Estimated implementation cost (optional)",
            "The expensive resource is analyst time; the system is pay-per-use")
    alerts, mins = n["rule_engine"]["alerts"], n["analyst_minutes_per_alert"]
    hours = alerts * mins / 60
    w = (WIDTH - 0.3) / 2
    left = [para("Analyst time today", 12, INK, SEMI, after=6),
            para(f"{hours:,.0f} h", 26, BLUE, SEMI),
            para(f"to review the {alerts:,} alerts our rule engine raised on the SAML-D sample, at {mins} min "
                 f"each (an industry estimate). Every 1% of alerts cleared safely saves {hours / 100:,.0f} hours.",
                 10, INK, line=1.05, after=6),
            para("Auto-close only when all six gate conditions pass, so the saving is bounded by safety, not by the model's eagerness.",
                 10, MUTED, line=1.05)]
    card_box = dict(fill=CARD, geom="roundRect", inset=0.14, radius=0.05)
    box(s, LEFT, TOP + 0.05, w, 2.75, left, **card_box)
    rt = n["runtime"]
    right = [para("Running cost per case", 12, INK, SEMI, after=6),
             para(f"**Gemini calls:** {rt['llm_calls_per_case']} per case (typology, evidence agents, up to 3 drafts).", 10, bullet=True, after=4),
             para(f"**Latency:** p50 {rt['latency_p50_s']} s, p95 {rt['latency_p95_s']} s on real data; the tail is quota back-off.",
                  10, bullet=True, after=4),
             para("**Serving:** Cloud Run scales to zero; Firestore, BigQuery and Storage are billed per use.", 10, bullet=True, after=4),
             para("**Data:** OFAC lists are public; transactions stay in the bank's own BigQuery.", 10, bullet=True, after=4)]
    if n.get("gemini_cost_per_case_usd") is not None:
        right.append(para(f"**Gemini spend:** about ${n['gemini_cost_per_case_usd']:.3f} per case (Cloud Billing).", 10, bullet=True))
    box(s, LEFT + w + 0.3, TOP + 0.05, w, 2.75, right, **card_box)


def s_snapshots(s: Slide) -> None:
    heading(s, "Snapshots of the prototype", "The analyst console: decision, gate, verifier drafts and the reversal")
    shots = HERE / "screenshots"
    # case_result 1848x1074 (1.72:1), reversal 1848x249 (7.42:1), ledger 1848x1110
    picture(s, shots / "case_result.jpg", LEFT, TOP + 0.05, 5.4, 5.4 / 1.721, "Decision, policy gate and verifier drafts")
    picture(s, shots / "reversal.jpg", 5.95, TOP + 0.05, 3.65, 3.65 / 7.42, "The reversal, three ways")
    picture(s, shots / "ledger.jpg", 5.95, TOP + 0.75, 3.65, 3.65 / 1.665, "Claim ledger with two timestamps")
    box(s, 5.9, TOP + 0.75 + 3.65 / 1.665 + 0.05, 3.75, 0.7,
        para("Demo bundle (fictional customer), recorded locally on scripted models. The deployed URL runs the same console on Gemini.",
             8.5, MUTED, line=1.0), inset=0.03)


def s_bench(s: Slide, n: dict) -> None:
    heading(s, "Prototype Performance report/Benchmarking",
            "Same golden alerts for every arm; the bar is zero suspicious alerts auto-closed")
    head = ["Arm", "What runs", "Suspicious auto-closed", "Auto-close rate", "Citation coverage", "Invented entities", "ECE", "n"]
    rows = [head]
    tones = {}
    for r, a in enumerate(n["arms"], start=1):
        sac = a["suspicious_auto_closed"]
        rows.append([a["arm"], a["what"], "running" if sac is None else sac, fmt_pct(a["auto_close_rate"]),
                     "—" if a["citation_coverage"] is None and a["n"] else fmt_pct(a["citation_coverage"]),
                     "—" if a["hallucinated_entities"] is None and a["n"] else fmt_pct(a["hallucinated_entities"]),
                     "—" if a["ece"] is None and a["n"] else ("running" if a["ece"] is None else f"{a['ece']:.2f}"),
                     "running" if a["n"] is None else str(a["n"])])
        if sac and not sac.startswith("0"):
            tones[(r, 2)] = RED
        if a["citation_coverage"] == 1.0:
            tones[(r, 4)] = GREEN
    table(s, LEFT, TOP + 0.05, [0.75, 2.45, 1.25, 1.0, 1.05, 1.0, 0.85, 0.85], rows, row_h=0.36, sz=9.5, tones=tones)
    hero = n["hero"]
    y = TOP + 0.05 + 0.36 * len(rows) + 0.2
    w = (WIDTH - 0.25) / 2
    card(s, LEFT, y, w, 1.15, "Real Gemini, real data: the verifier at work",
         f"On the hero alert, draft 1 was rejected for {hero['draft1_uncited']} uncited judgment sentences; "
         f"draft 2 was {hero['draft2_coverage'] * 100:.0f}% cited and accepted.", tone="blue", title_sz=11, body_sz=9.5)
    card(s, LEFT + w + 0.25, y, w, 1.15, "How to read it",
         "A1 is plain Gemini on the same alerts. A4-naive vs A4 isolates the clock. ECE: gap between stated "
         "confidence and real hit rate (lower is better).", title_sz=11, body_sz=9.5)


def s_future(s: Slide) -> None:
    heading(s, "Additional Details/Future Development (if any)", C.FUTURE_HEADLINE)
    w = (WIDTH - 0.3) / 2
    for k, (title, items) in enumerate(C.FUTURE):
        card(s, LEFT + k * (w + 0.3), TOP + 0.05, w, 2.3, title, items, tone="blue" if k == 0 else None,
             title_sz=13, body_sz=10.5, bullets=True)
    box(s, LEFT - 0.08, TOP + 2.55, WIDTH, 0.5,
        para("Our rule: in regulated finance, knowing when to hand a decision to a human is a feature, not a failure.",
             11, MUTED), inset=0.08)


def s_links(s: Slide, video: str) -> None:
    heading(s, "Provide links to your:", "Everything a judge needs to try it")
    items = [("GitHub Public Repository", REPO), ("Demo Video Link (3 Minutes)", video or "to be added"),
             ("Final Product Link", APP)]
    y = TOP + 0.15
    for k, (label, url) in enumerate(items):
        box(s, LEFT, y, 0.5, 0.5, para(str(k + 1), 14, WHITE, SEMI, align="ctr"), fill=BLUE, geom="ellipse",
            anchor="ctr", inset=0)
        box(s, LEFT + 0.7, y - 0.05, 8.4, 0.62, [para(label, 13, INK, SEMI), para(url, 12, BLUE)], inset=0.02)
        y += 0.95
    box(s, LEFT - 0.08, y + 0.05, WIDTH, 0.6,
        para("Try it: open the product link, pick the hero alert and press “Run the reversal”.", 11, MUTED), inset=0.08)


# ---------------------------------------------------------------- package surgery

def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def drop_text_boxes(xml: str) -> str:
    return re.sub(r"<p:sp>(?:(?!</p:sp>).)*?txBox=\"1\".*?</p:sp>", "", xml, flags=re.S)


def build(template: Path, out: Path, leader: str, video: str, numbers: dict) -> None:
    work = Path(tempfile.mkdtemp())
    try:
        with zipfile.ZipFile(template) as z:
            z.extractall(work)
        ppt = work / "ppt"
        pres, pres_rels = ppt / "presentation.xml", ppt / "_rels" / "presentation.xml.rels"
        ptxt, rtxt = _read(pres), _read(pres_rels)
        rid_of = {int(m.group(2)): m.group(1) for m in
                  re.finditer(r'Id="(rId\d+)"[^>]*Target="slides/slide(\d+)\.xml"', rtxt)}
        if not rid_of:
            rid_of = {int(m.group(1)): m.group(2) for m in
                      re.finditer(r'Target="slides/slide(\d+)\.xml"[^>]*Id="(rId\d+)"', rtxt)}
        ids = dict(re.findall(r'<p:sldId id="(\d+)" r:id="(rId\d+)"/>', ptxt))
        id_of = {rid: sid for sid, rid in ids.items()}
        lst = "".join(f'<p:sldId id="{id_of[rid_of[k]]}" r:id="{rid_of[k]}"/>' for k in ORDER)
        ptxt = re.sub(r"<p:sldIdLst>.*?</p:sldIdLst>", f"<p:sldIdLst>{lst}</p:sldIdLst>", ptxt, flags=re.S)
        pres.write_text(ptxt, encoding="utf-8")

        ct_path = work / "[Content_Types].xml"
        ct = _read(ct_path)
        for gone in sorted(set(rid_of) - set(ORDER)):
            rtxt = re.sub(rf'<Relationship [^>]*Target="slides/slide{gone}\.xml"/>', "", rtxt)
            srels = ppt / "slides" / "_rels" / f"slide{gone}.xml.rels"
            notes = re.findall(r'notesSlides/(notesSlide\d+)\.xml', _read(srels)) if srels.exists() else []
            for f in [ppt / "slides" / f"slide{gone}.xml", srels]:
                f.unlink(missing_ok=True)
            ct = ct.replace(f'<Override PartName="/ppt/slides/slide{gone}.xml" '
                            f'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>', "")
            for nn in notes:
                (ppt / "notesSlides" / f"{nn}.xml").unlink(missing_ok=True)
                (ppt / "notesSlides" / "_rels" / f"{nn}.xml.rels").unlink(missing_ok=True)
                ct = re.sub(rf'<Override PartName="/ppt/notesSlides/{nn}\.xml"[^>]*/>', "", ct)
        ct = re.sub(rf'<Override PartName="/ppt/slides/slide({"|".join(str(g) for g in set(rid_of) - set(ORDER))})\.xml"[^>]*/>', "", ct)
        if 'Extension="jpg"' not in ct:
            ct = ct.replace("<Default ", '<Default Extension="jpg" ContentType="image/jpeg"/><Default ', 1)
        ct_path.write_text(ct, encoding="utf-8")
        pres_rels.write_text(rtxt, encoding="utf-8")

        fill = {
            1: lambda s: s_team(s, leader), 3: lambda s: s_idea(s, numbers), 4: s_opps, 5: s_features,
            15: lambda s: s_reversal(s, numbers), 6: s_flow, 8: s_arch, 9: s_tech,
            10: lambda s: s_cost(s, numbers), 11: s_snapshots, 12: lambda s: s_bench(s, numbers),
            13: s_future, 14: lambda s: s_links(s, video),
        }
        media = ppt / "media"
        for num, fn in fill.items():
            path = ppt / "slides" / f"slide{num}.xml"
            s = Slide()
            fn(s)
            xml = drop_text_boxes(_read(path))
            xml = xml.replace("</p:spTree>", "".join(s.parts) + "</p:spTree>", 1)
            path.write_text(xml, encoding="utf-8")
            if s.images:
                rels = ppt / "slides" / "_rels" / f"slide{num}.xml.rels"
                rt = _read(rels)
                for rid, src in s.images:
                    name = f"prov_{src.stem}.jpg"
                    shutil.copyfile(src, media / name)
                    rt = rt.replace("</Relationships>",
                                    f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/'
                                    f'2006/relationships/image" Target="../media/{name}"/></Relationships>')
                rels.write_text(rt, encoding="utf-8")

        used = {m for r in work.rglob("*.rels") for m in re.findall(r'media/([^"]+)"', _read(r))}
        for f in media.iterdir():  # art only the dropped slides used
            if f.name not in used:
                f.unlink()

        out.parent.mkdir(parents=True, exist_ok=True)
        out.unlink(missing_ok=True)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            ct_first = work / "[Content_Types].xml"
            z.write(ct_first, "[Content_Types].xml")
            for f in sorted(work.rglob("*")):
                if f.is_file() and f != ct_first:
                    z.write(f, f.relative_to(work).as_posix())
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--template", type=Path, required=True)
    ap.add_argument("--leader", default="", help="team leader's full name (kept out of the repo)")
    ap.add_argument("--video", default="", help="public or unlisted demo video URL")
    ap.add_argument("--numbers", type=Path, default=HERE / "numbers.json")
    ap.add_argument("-o", "--out", type=Path, default=Path("Provenance_Deck.pptx"))
    a = ap.parse_args()
    build(a.template, a.out, a.leader, a.video, json.loads(a.numbers.read_text()))
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
