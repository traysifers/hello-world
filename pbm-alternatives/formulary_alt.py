#!/usr/bin/env python3
"""
formulary_alt.py - therapeutic alternatives for a "non-formulary, please
consider alternative" pharmacy message.

Give it the drug name (or paste the whole pharmacy message) and it prints a
plain-text note for the prior-authorization specialist listing every
same-class alternative with dose equivalence, ready to paste into the
NextGen telephone-communication box.

    python3 formulary_alt.py "Advair Diskus 250/50"
    python3 formulary_alt.py "Rx change: Dulera 100/5 non-formulary" --patient "J. Doe"
    python3 formulary_alt.py "clobetasol 0.05% cream" --pbm Caremark
    python3 formulary_alt.py --record covered --pbm Caremark "Wixela 250/50"
    python3 formulary_alt.py --list
    python3 formulary_alt.py --show ics-laba

Standard library only. Data lives in alternatives.json next to this file;
what each PBM has covered or denied before accumulates in
formulary_memory.json so later messages can flag it.
"""

import argparse
import difflib
import json
import os
import re
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(HERE, "alternatives.json")
MEMORY_PATH = os.path.join(HERE, "formulary_memory.json")

FORM_WORDS = {
    "hfa", "dpi", "mdi", "neb", "nebulizer", "nasal", "ophthalmic", "topical",
    "oral", "cream", "ointment", "gel", "lotion", "foam", "solution", "spray",
    "inhaler", "tablet", "capsule", "suspension", "sc", "iv", "generic",
}

# --------------------------------------------------------------------------
# data loading
# --------------------------------------------------------------------------


def load_data(path=DATA_PATH):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_memory(path=MEMORY_PATH):
    if not os.path.exists(path):
        return {"records": []}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_memory(mem, path=MEMORY_PATH):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(mem, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


# --------------------------------------------------------------------------
# text helpers
# --------------------------------------------------------------------------


def normalize(text):
    t = text.lower()
    t = re.sub(r"(\d)\s*-\s*(\d)", r"\1/\2", t)      # 250-50 -> 250/50
    t = re.sub(r"(\d)\s*/\s*(\d)", r"\1/\2", t)      # 250 / 50 -> 250/50
    t = t.replace("µg", "mcg").replace("ug", "mcg") if "ug" in t and "mcg" not in t else t
    t = re.sub(r"[^a-z0-9/.%\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def clean_brand(brand):
    return re.sub(r"\s*\(.*?\)", "", brand).strip().lower()


def numeric_tuple(text):
    """All numbers in `text` as a tuple of floats, e.g. '250/50 mcg' -> (250.0, 50.0)."""
    return tuple(float(n) for n in re.findall(r"\d+(?:\.\d+)?", text))


def find_strength_tokens(text):
    """Candidate strength strings in free text: 250/50, 0.05%, 20 mg, 110 ..."""
    pats = [
        r"\d+(?:\.\d+)?/\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?\s*(?:mcg|mg)?",
        r"\d+(?:\.\d+)?\s*%",
        r"\d+(?:\.\d+)?\s*(?:mcg|mg|iu|units?)\b",
        r"\b\d+(?:\.\d+)?\b",
    ]
    found = []
    for p in pats:
        for m in re.finditer(p, text):
            s = m.group(0).strip()
            if s not in found:
                found.append(s)
    return found


def fmt_num(x):
    return ("%g" % x) if x != int(x) else str(int(x))


# --------------------------------------------------------------------------
# matching
# --------------------------------------------------------------------------


COMPONENT_STOP = {"immune", "house", "short", "peanut", "timothy", "human", "recombinant",
                  "compounded", "swallowed", "augmented", "esterase", "globulin", "grass",
                  "extract", "allergen", "pollen", "nasal", "inhaled", "topical", "oral"}


def agent_id(agent):
    first = agent["brands"][0] if agent.get("brands") else ""
    return agent["generic"] + "|" + clean_brand(first)


def agent_aliases(agent):
    strong = {clean_brand(b) for b in agent.get("brands", [])}
    strong |= {a.lower() for a in agent.get("aliases", [])}
    generic = agent["generic"].lower()
    weak = {generic}
    # components of a combination and bare drug stems: "fluticasone", "salmeterol"
    for part in re.split(r"[/+]", re.sub(r"\(.*?\)", "", generic)):
        words = [w for w in part.split() if w not in FORM_WORDS]
        if words:
            weak.add(" ".join(words))
            if len(words[0]) >= 6 and words[0] not in COMPONENT_STOP:
                weak.add(words[0])
    strong.discard("")
    strong.discard("generic")
    return strong, weak - strong


def match_agents(data, text):
    """Return list of (score, strong, class_key, agent) for agents named in text."""
    norm = normalize(text)
    words = [w for w in norm.split() if w.isalpha() and len(w) >= 4]
    hits = []
    for ckey, cls in data["classes"].items():
        for agent in cls["agents"]:
            strong, weak = agent_aliases(agent)
            best = None
            for alias in strong | weak:
                if not alias:
                    continue
                if re.search(r"(?<![a-z])" + re.escape(alias) + r"(?![a-z])", norm):
                    sc = len(alias) + (100 if alias in strong else 0)
                    if best is None or sc > best[0]:
                        best = (sc, alias in strong, alias)
            if best:
                hits.append((best[0], best[1], ckey, agent, best[2]))
    if not hits:
        # fuzzy single-word match against brands/aliases (typos), only if nothing matched exactly
        for ckey, cls in data["classes"].items():
            for agent in cls["agents"]:
                strong, _ = agent_aliases(agent)
                single = [a for a in strong if " " not in a and len(a) >= 4]
                for w in words:
                    close = difflib.get_close_matches(w, single, n=1, cutoff=0.86)
                    if close:
                        hits.append((len(close[0]) + 50, True, ckey, agent, close[0]))
                        break
    if any(h[1] for h in hits):
        hits = [h for h in hits if h[1]]
    pruned = []
    for h in hits:
        shadowed = any(
            agent_id(o[3]) != agent_id(h[3]) and len(o[4]) > len(h[4])
            and re.search(r"(?<![a-z])" + re.escape(h[4]) + r"(?![a-z])", o[4])
            for o in hits)
        if not shadowed:
            pruned.append(h)
    pruned.sort(key=lambda h: -h[0])
    return pruned


def detect_tier(cls, agent, text):
    """Work out the denied drug's tier (dose tier / potency class / weight dose)."""
    tiers = cls.get("tiers")
    if not tiers:
        return None, None
    norm = normalize(text)
    for kw, tier in (cls.get("tier_keywords") or {}).items():
        if re.search(r"\b" + re.escape(kw) + r"\b", norm):
            return tier, kw
    strengths = agent.get("strengths") or {}
    if not strengths:
        return None, None
    tokens = find_strength_tokens(norm)
    vehicle_words = {w for w in norm.split() if w in FORM_WORDS}
    candidates = []
    for tok in tokens:
        nt = numeric_tuple(tok)
        if not nt:
            continue
        for key, tier in strengths.items():
            if numeric_tuple(key) != nt:
                continue
            key_vehicle = {w for w in key.lower().split() if w in FORM_WORDS}
            if key_vehicle and vehicle_words and not (key_vehicle & vehicle_words):
                continue
            candidates.append((tier, key))
        if candidates:
            break
    if not candidates:
        return None, None
    distinct = {c[0] for c in candidates}
    if len(distinct) == 1:
        return candidates[0][0], candidates[0][1]
    # same number maps to several tiers (e.g. 0.1% cream vs ointment)
    return None, " or ".join(sorted({c[1] for c in candidates}))


def detect_mg(text):
    m = re.search(r"(\d+(?:\.\d+)?)\s*mg\b", normalize(text))
    return float(m.group(1)) if m else None


# --------------------------------------------------------------------------
# memory (what each PBM covered / denied before)
# --------------------------------------------------------------------------


def memory_tags(mem, agent, pbm=None):
    tags = []
    for rec in mem.get("records", []):
        if rec.get("id", rec.get("generic")) != agent_id(agent):
            continue
        if pbm and pbm.lower() not in rec.get("pbm", "").lower():
            continue
        when = rec.get("date", "")[:7]
        tags.append("%s on %s %s" % (rec["status"], rec["pbm"], when))
    return tags


def add_record(mem, pbm, status, drug_text, ckey, agent, note=""):
    rec = {
        "pbm": pbm,
        "status": status,
        "drug": drug_text,
        "generic": agent["generic"],
        "id": agent_id(agent),
        "class": ckey,
        "date": date.today().isoformat(),
    }
    if note:
        rec["note"] = note
    # replace an older record for the same pbm/drug/status
    mem["records"] = [
        r for r in mem.get("records", [])
        if not (r["pbm"].lower() == pbm.lower() and r.get("id", r.get("generic")) == agent_id(agent)
                and r["status"] == status)
    ]
    mem["records"].append(rec)
    return rec


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------


def label_for(agent, alias):
    """Proper-cased name for the denied drug: the brand the user named, else the generic."""
    for b in agent.get("brands", []):
        cb = clean_brand(b)
        if cb == alias:
            return re.sub(r"\s*\(.*?\)", "", b).strip()
    if alias in {a.lower() for a in agent.get("aliases", [])}:
        for b in agent.get("brands", []):
            if clean_brand(b).startswith(alias) or alias.startswith(clean_brand(b)):
                return re.sub(r"\s*\(.*?\)", "", b).strip()
    return agent["generic"]


def brand_list(agent):
    names = [re.sub(r"\s*\(.*?\)", "", b).strip() for b in agent.get("brands", [])]
    names = [n for n in names if n.lower() != "generic"]
    return ", ".join(names)


def coverage_flags(agent):
    flags = []
    if agent.get("otc"):
        flags.append("OTC")
    flags.append("generic available" if agent.get("generic_available") else "brand only")
    return "; ".join(flags)


def tier_distance(tiers, a, b):
    try:
        return abs(tiers.index(a) - tiers.index(b))
    except ValueError:
        return 99


def tier_phrase(cls, tier):
    label = cls.get("tier_label", "tier")
    note = (cls.get("tier_notes") or {}).get(tier)
    s = "%s %s" % (tier, label) if not label.startswith("potency") else "potency class %s" % tier
    if label == "ICS dose tier":
        s = "%s-dose ICS tier" % tier
    if label == "weight-based dose":
        s = "%s dose" % tier
    if note:
        s += " (%s)" % note
    return s


def render_alternative(cls, agent, tier, denied_mg, denied_agent, mem, pbm):
    tiers = cls.get("tiers")
    name = agent["generic"][0].upper() + agent["generic"][1:]
    brands = brand_list(agent)
    head = "%s (%s)" % (name, brands) if brands else name
    strength_part = ""
    equiv = ""
    strengths = agent.get("strengths") or {}

    if tiers and tier and strengths:
        same = [k for k, t in strengths.items() if t == tier]
        if same:
            strength_part = " " + " or ".join(same)
            equiv = "%s equivalent" % tier_phrase(cls, tier)
        else:
            # nearest tier available for this agent
            best = min(strengths.items(), key=lambda kv: tier_distance(tiers, kv[1], tier))
            d = tier_distance(tiers, best[1], tier)
            if len(tiers) > 3 and d > 1:
                return None   # too far off (e.g. class 1 vs class 5 steroid)
            strength_part = " " + best[0]
            direction = ""
            if tiers.index(best[1]) < tiers.index(tier):
                direction = "lower" if len(tiers) <= 3 else "stronger"
            else:
                direction = "higher" if len(tiers) <= 3 else "weaker"
            if cls.get("tier_label") == "weight-based dose":
                return None   # no matching weight-dose; skip
            equiv = "no %s option; nearest is %s (%s, one step %s)" % (
                tier_phrase(cls, tier), best[0], tier_phrase(cls, best[1]), direction)
    elif tiers and strengths:
        strength_part = " " + ", ".join("%s (%s)" % (k, t) for k, t in strengths.items())
    elif cls.get("equivalence") == "glucocorticoid" and denied_mg and denied_agent:
        eq_mg = denied_mg / denied_agent["equiv_mg"] * agent["equiv_mg"]
        equiv = "%s mg ~ %s %s mg" % (fmt_num(eq_mg), denied_agent["generic"], fmt_num(denied_mg))
    elif cls.get("equivalence") == "glucocorticoid":
        equiv = "%s mg ~ prednisone 5 mg" % fmt_num(agent["equiv_mg"])

    parts = ["- %s%s - %s, %s" % (head, strength_part, agent.get("device", ""), agent.get("frequency", ""))]
    tail = []
    if equiv:
        tail.append(equiv)
    if agent.get("note"):
        tail.append(agent["note"])
    for flag in coverage_flags(agent).split("; "):
        if flag.lower() not in agent.get("note", "").lower():
            tail.append(flag)
    tags = memory_tags(mem, agent, pbm)
    if tags:
        tail.append("[" + "; ".join(tags) + "]")
    return parts[0] + " - " + "; ".join(tail)


def render_section(data, ckey, agent, text, mem, pbm, denied_label):
    cls = data["classes"][ckey]
    tier, tier_src = detect_tier(cls, agent, text)
    denied_mg = detect_mg(text) if cls.get("equivalence") == "glucocorticoid" else None
    lines = []
    denied_line = "Denied: %s - %s - %s" % (denied_label, cls["name"], cls["indication"])
    if tier:
        denied_line += " - %s" % tier_phrase(cls, tier)
    elif tier_src:
        denied_line += " - strength matches %s; specify vehicle to pin the potency class" % tier_src
    elif cls.get("tiers") and agent.get("strengths"):
        denied_line += " - strength not given; alternatives listed at every tier"
    if denied_mg and cls.get("equivalence") == "glucocorticoid":
        denied_line += " - %s mg" % fmt_num(denied_mg)
    lines.append(denied_line)
    lines.append("")
    lines.append("Alternatives:")
    alts = []
    for other in cls["agents"]:
        if other is agent:
            continue
        r = render_alternative(cls, other, tier, denied_mg, agent, mem, pbm)
        if r:
            alts.append((other, r))
    if cls.get("tiers") and tier:
        # same tier first, then nearest
        def sort_key(item):
            st = item[0].get("strengths") or {}
            d = min((tier_distance(cls["tiers"], t, tier) for t in st.values()), default=99)
            return (d, 0 if item[0].get("generic_available") else 1)
        alts.sort(key=sort_key)
    else:
        alts.sort(key=lambda item: 0 if item[0].get("generic_available") else 1)
    if alts:
        lines.extend(r for _, r in alts)
    else:
        lines.append("- No same-class alternative exists for this product.")
    if cls.get("specialty"):
        lines.append("")
        lines.append("Note: these are specialty agents with different indications and age cut-offs. "
                     "A switch is a clinical decision, not a straight swap - please send the "
                     "plan's preferred-agent list back to the prescriber, or submit a PA / medical "
                     "exception for the original drug.")
    related = [data["classes"][r]["name"] for r in cls.get("related", []) if r in data["classes"]]
    if related and (not alts or len(alts) <= 2):
        lines.append("")
        lines.append("Related classes to consider if nothing above is covered: " + "; ".join(related) + ".")
    return lines, tier


def render_message(data, hits, text, patient, mem, pbm, strength_text):
    agent = hits[0][3]
    label = label_for(agent, hits[0][4])
    if strength_text and numeric_tuple(strength_text) != numeric_tuple(label):
        label += " " + strength_text
    vehicle = [w for w in normalize(text).split()
               if w in {"cream", "ointment", "gel", "lotion", "foam", "solution", "spray", "oil"}]
    if vehicle and vehicle[0] not in label.lower():
        label += " " + vehicle[0]
    opener = "Pharmacy sent an Rx-change request for %s%s; it is not covered under the patient's plan." % (
        label, " (%s)" % patient if patient else "")
    body = [opener, ""]
    sections = []
    for _, _, ckey, ag, _ in hits:
        if agent_id(ag) != agent_id(agent) or ckey in [c for c, _ in sections]:
            continue
        sec, _ = render_section(data, ckey, ag, text, mem, pbm, label)
        sections.append((ckey, sec))
    for i, (ckey, sec) in enumerate(sections):
        if len(sections) > 1:
            if i:
                body.append("")
            body.append("If prescribed for %s:" % data["classes"][ckey]["indication"])
        body.extend(sec)
    body.append("")
    body.append("Please review the formulary, pick the best covered option above, and task "
                "clinical staff to send in the new Rx. Thank you!")
    return "\n".join(body)


def strength_from_text(cls_list, agent, text):
    """The strength string as the user typed it, cleaned, for the message label."""
    norm = normalize(text)
    for tok in find_strength_tokens(norm):
        nt = numeric_tuple(tok)
        for cls in cls_list:
            for key in (agent.get("strengths") or {}):
                if numeric_tuple(key) == nt:
                    return key
        if "/" in tok or "%" in tok or re.search(r"mg|mcg", tok):
            return tok
    return ""


# --------------------------------------------------------------------------
# listing helpers
# --------------------------------------------------------------------------


def list_classes(data):
    for key, cls in data["classes"].items():
        print("%-22s %s  [%d agents]" % (key, cls["name"], len(cls["agents"])))


def show_class(data, key):
    cls = data["classes"].get(key)
    if not cls:
        close = difflib.get_close_matches(key, data["classes"].keys(), n=3, cutoff=0.5)
        sys.exit("Unknown class '%s'. Did you mean: %s" % (key, ", ".join(close) or "(see --list)"))
    print("%s - %s" % (cls["name"], cls["indication"]))
    if cls.get("tiers"):
        print("Tiers (%s): %s" % (cls.get("tier_label", "tier"), ", ".join(cls["tiers"])))
    print()
    for a in cls["agents"]:
        st = a.get("strengths")
        st_s = " | " + ", ".join("%s=%s" % (k, v) for k, v in st.items()) if st else ""
        print("- %s (%s)%s" % (a["generic"], brand_list(a) or "generic", st_s))
        print("    %s, %s" % (a.get("device", ""), a.get("frequency", "")))
        print("    %s; %s" % (a.get("note", ""), coverage_flags(a)))


def disambiguate(hits):
    print("That name matches more than one product. Re-run with the brand name, or add --class KEY:", file=sys.stderr)
    seen = set()
    for _, _, ckey, agent, alias in hits:
        k = (ckey, agent_id(agent))
        if k in seen:
            continue
        seen.add(k)
        print("  --class %-20s %s (%s)" % (ckey, agent["generic"], brand_list(agent) or "generic"), file=sys.stderr)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Therapeutic alternatives for a non-formulary pharmacy message.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Standard library")[0])
    ap.add_argument("text", nargs="*", help="drug name, strength, or the pasted pharmacy message")
    ap.add_argument("--patient", help="patient name to include in the opener")
    ap.add_argument("--pbm", help="PBM / plan name (annotates alternatives with that plan's history and records this denial)")
    ap.add_argument("--class", dest="cls", help="force a class key when a name is ambiguous (see --list)")
    ap.add_argument("--all", action="store_true", help="when ambiguous, print a message for every match")
    ap.add_argument("--record", choices=["covered", "denied"], help="store that TEXT was covered/denied by --pbm, then exit")
    ap.add_argument("--note", default="", help="free-text note for --record")
    ap.add_argument("--no-record", action="store_true", help="do not auto-record the denial when --pbm is given")
    ap.add_argument("--json", action="store_true", help="machine-readable output instead of the message")
    ap.add_argument("--list", action="store_true", help="list drug classes and exit")
    ap.add_argument("--show", metavar="CLASS", help="print a whole class table and exit")
    ap.add_argument("--history", action="store_true", help="print the PBM coverage memory and exit")
    ap.add_argument("--data", default=DATA_PATH, help="path to alternatives.json")
    ap.add_argument("--memory", default=MEMORY_PATH, help="path to formulary_memory.json")
    args = ap.parse_args(argv)

    data = load_data(args.data)
    mem = load_memory(args.memory)

    if args.list:
        list_classes(data)
        return 0
    if args.show:
        show_class(data, args.show)
        return 0
    if args.history:
        for r in mem.get("records", []):
            print("%s  %-8s %-18s %s  (%s)%s" % (r["date"], r["status"], r["pbm"], r["drug"], r["class"],
                                                  "  - " + r["note"] if r.get("note") else ""))
        if not mem.get("records"):
            print("No PBM history recorded yet. Use --pbm NAME with a message, or --record covered/denied.")
        return 0

    text = " ".join(args.text).strip()
    if not text:
        if sys.stdin.isatty():
            try:
                text = input("Paste the pharmacy message or type the drug name: ").strip()
            except EOFError:
                text = ""
        else:
            text = sys.stdin.read().strip()
    if not text:
        ap.print_usage()
        return 1

    hits = match_agents(data, text)
    if args.cls:
        if args.cls not in data["classes"]:
            sys.exit("Unknown class '%s' (see --list)" % args.cls)
        hits = [h for h in hits if h[2] == args.cls]
    if not hits:
        print("No drug in the database matched: %r" % text, file=sys.stderr)
        print("Try the brand name, run --list to see classes, or add the product to alternatives.json.", file=sys.stderr)
        return 2

    distinct_generics = []
    for h in hits:
        if agent_id(h[3]) not in distinct_generics:
            distinct_generics.append(agent_id(h[3]))

    if args.record:
        if not args.pbm:
            sys.exit("--record needs --pbm NAME")
        if len(distinct_generics) > 1 and not args.cls:
            disambiguate(hits)
            return 2
        rec = add_record(mem, args.pbm, args.record, text, hits[0][2], hits[0][3], args.note)
        save_memory(mem, args.memory)
        print("Recorded: %s %s on %s (%s)" % (rec["generic"], rec["status"], rec["pbm"], rec["date"]))
        return 0

    if len(distinct_generics) > 1 and not args.all:
        disambiguate(hits)
        return 2

    groups = [distinct_generics] if not args.all else [[g] for g in distinct_generics]
    outputs = []
    for group in groups:
        ghits = [h for h in hits if agent_id(h[3]) in group]
        agent = ghits[0][3]
        cls_list = [data["classes"][h[2]] for h in ghits]
        strength_text = strength_from_text(cls_list, agent, text)
        if args.pbm and not args.no_record:
            add_record(mem, args.pbm, "denied", text, ghits[0][2], agent)
            save_memory(mem, args.memory)
            print("(recorded: %s denied on %s)" % (agent["generic"], args.pbm), file=sys.stderr)
        if args.json:
            sections = []
            for h in ghits:
                cls = data["classes"][h[2]]
                tier, _ = detect_tier(cls, agent, text)
                sections.append({
                    "class": h[2], "class_name": cls["name"], "indication": cls["indication"],
                    "tier": tier, "specialty": bool(cls.get("specialty")),
                    "alternatives": [
                        dict(a, memory=memory_tags(mem, a, args.pbm))
                        for a in cls["agents"] if a is not agent],
                })
            outputs.append({"denied": {"generic": agent["generic"], "brands": agent.get("brands", []),
                                       "strength": strength_text, "input": text},
                            "patient": args.patient, "pbm": args.pbm, "sections": sections})
        else:
            outputs.append(render_message(data, ghits, text, args.patient, mem, args.pbm, strength_text))

    if args.json:
        print(json.dumps(outputs if args.all else outputs[0], indent=2, ensure_ascii=False))
    else:
        print(("\n\n" + "=" * 70 + "\n\n").join(outputs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
