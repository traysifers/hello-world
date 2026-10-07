# PBM formulary alternatives

When the pharmacy sends "**medication is non-formulary, please consider alternative**", paste
that message (or just the drug name) into this tool. It prints a plain-text note for the
prior-authorization specialist that lists every same-class alternative with dose
equivalence, in the same format as the existing inhaler-switch message, ready to paste into
the NextGen telephone-communication box.

It needs only Python 3 (3.8 or newer). No installs.

## Quick start

```bash
cd pbm-alternatives

python3 formulary_alt.py "Advair Diskus 250/50"
python3 formulary_alt.py "Rx change: Dulera 100-5 mcg non-formulary, please consider alternative" --patient "J. Doe"
python3 formulary_alt.py "clobetasol 0.05% cream"
python3 formulary_alt.py "Orapred ODT 15 mg"
python3 formulary_alt.py "EpiPen Jr"
python3 formulary_alt.py                      # with no argument it prompts you to paste the message
```

Example output:

```
Pharmacy sent an Rx-change request for Advair Diskus 250/50 mcg (J. Doe); it is not covered under the patient's plan.

Denied: Advair Diskus 250/50 mcg - ICS/LABA combination inhaler - asthma controller (step 3+); also COPD - medium-dose ICS tier

Alternatives:
- Fluticasone propionate/salmeterol HFA (Advair HFA) 115/21 mcg - MDI, 2 puffs BID - medium-dose ICS tier equivalent; ...; generic available
- Fluticasone propionate/salmeterol breath-actuated (AirDuo RespiClick, AirDuo Digihaler) 113/14 mcg - ...
- Budesonide/formoterol (Symbicort, Breyna) 160/4.5 mcg - MDI, 2 puffs BID - medium-dose ICS tier equivalent; ...
- Fluticasone furoate/vilanterol (Breo Ellipta) 100/25 mcg - DPI, 1 inhalation once daily - ...
- Mometasone/formoterol (Dulera) 100/5 mcg - MDI, 2 puffs BID - ...

Please review the formulary, pick the best covered option above, and task clinical staff to send in the new Rx. Thank you!
```

## What it knows how to do

- **Dose tiers.** ICS and ICS/LABA inhalers are matched by low / medium / high tier, so Advair
  250/50 lists Symbicort 160/4.5, not 80/4.5. Topical steroids are matched by potency class
  (1 to 7) and only show the same class and the one next to it. Epinephrine is matched by
  weight band (EpiPen Jr lists the 0.15 mg devices and neffy 1 mg). Oral steroids convert the
  milligram dose (Orapred 15 mg shows methylprednisolone 12 mg, dexamethasone 2.25 mg).
- **Pasted messages.** It finds the drug and strength inside the pharmacy's wording and copes
  with "250-50", "250/50", typos like "symbicrot", and brand or generic names.
- **Ambiguity.** A bare "fluticasone" could be an inhaler, nasal spray or cream, so it lists the
  choices and you re-run with the brand or `--class incs`.
- **Drugs in more than one class.** Dupixent prints one section per indication (atopic
  dermatitis, asthma / CRSwNP / CSU, EoE).
- **Specialty agents.** Biologics, HAE drugs, immunoglobulin and SLIT tablets get a line saying
  the switch is a clinical decision and a PA or medical exception may be the better route.
- **Single-agent classes.** Atrovent nasal has no in-class swap, so it says so and names the
  related classes.

## Remembering what each PBM covers

The tool cannot see a plan's live formulary. What it can do is remember outcomes so the next
message for the same PBM is pre-annotated.

```bash
# the pharmacy message said Caremark would not cover Advair HFA: annotate with Caremark history
python3 formulary_alt.py "Advair HFA 115/21" --pbm Caremark
#   (the denial is recorded automatically; add --no-record to skip that)

# the PA specialist reports Wixela went through
python3 formulary_alt.py --record covered --pbm Caremark "Wixela 250/50" --note "approved 10/2026"

python3 formulary_alt.py --history       # everything recorded so far
```

After that, Caremark messages show `[covered on Caremark 2026-10]` or `[denied on Caremark ...]`
next to the matching alternatives. History lives in `formulary_memory.json` beside the script.
It stores drug, plan and date only, never patient information.

## Other commands

```bash
python3 formulary_alt.py --list              # the 28 drug classes and their keys
python3 formulary_alt.py --show ics-laba     # the whole table for one class
python3 formulary_alt.py "Breo 100/25" --json  # structured output for other tools
python3 -m unittest test_formulary_alt       # run the tests
```

## Editing the drug database

Everything clinical is in `alternatives.json`, grouped by class. Each agent has a generic name,
brands, aliases (what people type), device, frequency, a note, and `generic_available` / `otc`
flags. Classes with tiers give each strength a tier label. To add a product, copy a neighbouring
entry and edit it. The tests check that every tier label is valid and every related class exists.

Classes included: SABA (inhaled and nebulized), ICS, ICS/LABA, LAMA, LAMA/LABA, triple, LABA,
leukotriene modifiers, intranasal steroids, intranasal antihistamines and combinations, nasal
ipratropium, oral antihistamines, H2 blockers, ophthalmic allergy drops, epinephrine, oral
steroids, topical steroids, nonsteroidal topicals, systemic AD therapy, asthma / CSU biologics,
PPIs, swallowed steroids for EoE, HAE prophylaxis and on-demand, immunoglobulin, and SLIT /
OIT products.

## Caveats

Tiers and equivalences are approximate and follow GINA / NAEPP conventions for adults and
adolescents. Formularies change every year and vary by plan, so the output is a list of
candidates for the PA specialist to check, not a statement of coverage. Review clinically
before prescribing.
