"""
Hand-curated match criteria for the benchmark answer key.

Each entry is written after reading that trial's own eligibility text in
cache/nct/<id>.json. Nothing here comes from the model being benchmarked - an
answer key derived from the system under test measures nothing.

Conventions, following the first twelve trials curated by hand and verified
end-to-end in MatchMiner:

- One step, one `and` block at the top.
- Diagnoses are Oncotree display names under `or`; the pipeline is scored on
  the exact set, so a parent term instead of the child is a real difference.
- Age bounds come from the trial's own limits, in years, as separate
  `age_numerical` entries.
- `!` prefixes a negated variant_category, i.e. an exclusion.
- Alternative cohorts - the trial enrols patients both with and without an
  alteration - are `or` branches, not a bare requirement. Encoding them as a
  requirement is the error that makes a trial match nobody.
- Stratification is not eligibility. A biomarker that only assigns a risk
  group or an arm, while every group enrols, is NOT a genomic criterion.
"""


def dx(*names):
    """One diagnosis, or an `or` over several."""
    if len(names) == 1:
        return {"clinical": {"oncotree_primary_diagnosis": names[0]}}
    return {"or": [{"clinical": {"oncotree_primary_diagnosis": n}} for n in names]}


def gene(symbol, variant_category="Mutation", **extra):
    return {"genomic": {"hugo_symbol": symbol,
                        "variant_category": variant_category, **extra}}


def amplified(symbol, negated=False):
    return gene(symbol, "Copy Number Variation",
                cnv_call=("!High Amplification" if negated else "High Amplification"))


def fusion(symbol, negated=False):
    return gene(symbol, "!Structural Variation" if negated else "Structural Variation")


def any_of(*nodes):
    return {"or": list(nodes)}


def all_of(*nodes):
    return {"and": list(nodes)}


def age(expr):
    return {"clinical": {"age_numerical": expr}}


def status(*values):
    return {"clinical": {"disease_status": list(values)}}


CURATIONS = {}


# --------------------------------------------------------------- neuroblastoma
CURATIONS["NCT02559778"] = dict(
    # PLAN. MYCN amplification is one of several alternative routes in: stage 4
    # patients over 18 months qualify "regardless of biologic features", so
    # amplification is a cohort, not a requirement.
    age="Children",
    match=[all_of(
        any_of(
            all_of(dx("Neuroblastoma", "Ganglioneuroblastoma"), amplified("MYCN")),
            all_of(dx("Neuroblastoma", "Ganglioneuroblastoma"), age(">=1.5")),
        ),
        age("<=21"),
    )],
)

CURATIONS["NCT06172296"] = dict(
    # ANBL2131. Same shape: "any age ... and MYCN amplification" OR "age >= 547
    # days and INRG stage M regardless of biologic features".
    age="Children",
    match=[all_of(
        any_of(
            all_of(dx("Neuroblastoma", "Ganglioneuroblastoma"), amplified("MYCN")),
            all_of(dx("Neuroblastoma", "Ganglioneuroblastoma"), age(">=1.5")),
        ),
        age("<=30"),
    )],
)


# ---------------------------------------------------------------- bone sarcoma
CURATIONS["NCT05918640"] = dict(
    # Lurbinectedin in FET-fused tumours. The fusion IS the eligibility
    # criterion here, not a stratifier: "Patients must have a known FET fusion
    # (fusion that contains EWSR1, FUS, or TAF15)".
    age="All",
    match=[all_of(
        dx("Ewing Sarcoma", "Desmoplastic Small-Round-Cell Tumor"),
        any_of(fusion("EWSR1"), fusion("FUS"), fusion("TAF15")),
        age(">=10"),
        status("Recurrent", "Refractory"),
    )],
)


# ---------------------------------------------------------------- soft tissue
CURATIONS["NCT06023641"] = dict(
    # Newly diagnosed RMS, molecular risk stratification. FOXO1, MYOD1 and TP53
    # appear throughout the criteria but only to assign low/intermediate/high
    # risk, and all three groups enrol. No genomic criterion.
    age="Children",
    match=[all_of(
        dx("Rhabdomyosarcoma", "Embryonal Rhabdomyosarcoma",
           "Alveolar Rhabdomyosarcoma", "Spindle Cell/Sclerosing Rhabdomyosarcoma"),
        age("<22"),
    )],
)


# -------------------------------------------------------------------- leukaemia
CURATIONS["NCT05748171"] = dict(
    # Inotuzumab in first-relapse B-cell precursor ALL. KMT2A::AFF1, TCF3-HLF,
    # TCF3-PBX1 and TP53 separate high-risk from very-high-risk relapse, and
    # both strata enrol - HR is defined by *lacking* them. Stratification, not
    # eligibility.
    age="Children",
    match=[all_of(
        dx("B-Lymphoblastic Leukemia/Lymphoma, NOS"),
        age(">=1"), age("<18"),
        status("Recurrent"),
    )],
)

CURATIONS["NCT02443831"] = dict(
    # CARPALL CD19/CD22 CAR-T. Thirteen alternative qualifying routes, most of
    # them disease-burden or MRD based; the high-risk genetics are one route
    # among many, so nothing genomic is required of every patient.
    age="Children",
    match=[all_of(
        dx("B-Lymphoblastic Leukemia/Lymphoma, NOS"),
        age("<=24"),
        status("Recurrent", "Refractory"),
    )],
)

CURATIONS["NCT05366218"] = dict(
    # Tafasitamab post-transplant B-ALL. Four alternative routes joined by
    # "either ... or"; only the first names molecular alterations, the other
    # three are MRD- and transplant-history based.
    age="Children",
    match=[all_of(
        dx("B-Lymphoblastic Leukemia/Lymphoma, NOS"),
        age(">=3"), age("<18"),
        status("Recurrent", "Refractory"),
    )],
)

CURATIONS["NCT06177067"] = dict(
    # Revumenib. Here the genetics ARE required: "Presence of KMT2A
    # rearrangement, NUP98 rearrangement, NPM1 mutation or fusion,
    # PICALM::MLLT10, DEK::NUP214, UBTF-TD, KAT6A rearrangement, or
    # SET::NUP214". SET is not in the Kispi gene list, so the partner NUP214
    # carries that fusion; a key cannot require a symbol the prompt never
    # offers.
    age="Children",
    match=[all_of(
        dx("Acute Myeloid Leukemia", "Acute Leukemias of Ambiguous Lineage"),
        any_of(
            fusion("KMT2A"), fusion("NUP98"),
            gene("NPM1", "Mutation"), fusion("NPM1"),
            fusion("PICALM"), fusion("MLLT10"),
            fusion("DEK"), fusion("NUP214"),
            gene("UBTF", "Mutation"), fusion("KAT6A"),
        ),
        age(">=1"), age("<=30"),
        status("Recurrent", "Refractory"),
    )],
)

CURATIONS["NCT07012447"] = dict(
    # Three alternative diagnoses. Only the middle one carries a genomic
    # requirement - "T-ALL with myeloid mutations" - while ETP-like leukaemia
    # and T/My-MPAL qualify on immunophenotype alone.
    # t(8;21) is excluded too, but its partner RUNX1T1 is not in the gene list
    # and RUNX1 alone would contradict the inclusion above, so only t(15;17)
    # and inv(16) are encoded.
    age="All",
    match=[all_of(
        any_of(
            dx("Early T-Cell Precursor Lymphoblastic Leukemia"),
            all_of(
                dx("T-Lymphoblastic Leukemia/Lymphoma"),
                any_of(*[gene(g, "Mutation") for g in
                         ("FLT3", "DNMT3A", "STAG2", "IDH1", "IDH2", "RUNX1",
                          "EZH2", "WT1", "ASXL1", "ASXL2", "SF3B1", "TET2",
                          "BCOR", "BCORL1")]),
            ),
            dx("Mixed Phenotype Acute Leukemia, T/Myeloid, NOS"),
        ),
        age(">=14"),
        fusion("PML", negated=True),
        fusion("CBFB", negated=True),
    )],
)

CURATIONS["NCT07059975"] = dict(
    # UPDATE AML. The long list of recurrent abnormalities applies only to
    # patients with < 20% marrow blasts; anyone with >= 20% blasts enrols with
    # no genetics at all, so none of it is required.
    age="Children",
    match=[all_of(
        dx("Acute Myeloid Leukemia", "Myeloid Sarcoma"),
        age("<=30"),
    )],
)


# -------------------------------------------------------------------------- CNS
CURATIONS["NCT05180825"] = dict(
    # LOGGIC. Unusually, the molecular criteria here are all negative:
    # "negative BRAFv600 mutation", "midline tumors without proven histone H3
    # mutations", "diffuse glioma without IDH1 mutation". The KIAA1549-BRAF
    # fusion status is only "determined", never required.
    age="Children",
    match=[all_of(
        dx("Low-Grade Glioma, NOS", "Pleomorphic Xanthoastrocytoma",
           "Ganglioglioma", "Papillary Glioneuronal Tumor",
           "Rosette-forming Glioneuronal Tumor of the Fourth Ventricle"),
        age("<=25"),
        gene("BRAF", "!Mutation"),
        gene("IDH1", "!Mutation"),
        gene("H3-3A", "!Mutation"),
        gene("H3-3B", "!Mutation"),
        gene("H3C2", "!Mutation"),
    )],
)

CURATIONS["NCT07110246"] = dict(
    # "histologically confirmed LGG WHO Grade I or II with BRAF V600 mutation
    # confirmed by immunohistochemistry or sequencing" - required, not a
    # stratifier.
    age="Children",
    match=[all_of(
        dx("Low-Grade Glioma, NOS"),
        gene("BRAF", "Mutation"),
        age(">=1"), age("<=25"),
    )],
)

CURATIONS["NCT06528691"] = dict(
    # Entrectinib upfront in infants. The fusion is the eligibility criterion
    # for cohort 1: "High-grade glioma ... harboring NTRK1/2/3 or ROS1 gene
    # fusions as determined by central pathology review".
    age="Children",
    match=[all_of(
        dx("High-Grade Glioma, NOS"),
        any_of(fusion("NTRK1"), fusion("NTRK2"), fusion("NTRK3"), fusion("ROS1")),
        age("<3"),
    )],
)

CURATIONS["NCT04696029"] = dict(
    # DFMO maintenance. MYC, MYCN and TP53 define the three cohorts, and
    # cohort 1 is explicitly *non*-MYC amplified while cohort 3 is
    # relapsed/refractory disease with no molecular requirement at all. Every
    # cohort enrols, so nothing genomic is required.
    age="Children",
    match=[all_of(
        dx("Medulloblastoma"),
        age("<=21"),
    )],
)

CURATIONS["NCT07215910"] = dict(
    # Vorasidenib. Required: "Presence of IDH1 p.R132 or IDH2 p.172 mutation".
    # Excluded: "Absence of CDKN2A/B homozygous deletion by central testing".
    age="All",
    match=[all_of(
        dx("Astrocytoma, IDH-Mutant, Grade 3"),
        any_of(gene("IDH1", "Mutation"), gene("IDH2", "Mutation")),
        gene("CDKN2A", "Copy Number Variation", cnv_call="!Homozygous Deletion"),
        age(">=12"),
    )],
)


# ------------------------------------------------------- renal, liver, retinal
CURATIONS["NCT04322318"] = dict(
    # AREN1921. Diffuse anaplastic Wilms tumour and relapsed favourable
    # histology Wilms tumour; histology and relapse risk group decide the arm,
    # nothing molecular is required.
    age="Children",
    match=[all_of(dx("Wilms' Tumor"), age("<=30"))],
)

CURATIONS["NCT04478292"] = dict(
    # Newly diagnosed hepatoblastoma. No molecular eligibility at all - the
    # criteria are histology, performance status and organ function.
    age="Children",
    match=[all_of(dx("Hepatoblastoma"), age("<=18"))],
)

CURATIONS["NCT05504291"] = dict(
    # Intraocular retinoblastoma. Eligibility is by Group (A-E) and vitreous
    # seeding; RB1 is not mentioned in the inclusion criteria.
    age="Children",
    match=[all_of(dx("Retinoblastoma"), age("<18"))],
)

CURATIONS["NCT05985161"] = dict(
    # Selinexor. "XPO1 Gene Mutation" is listed as a trial condition but no
    # cohort requires it: A is any Wilms tumour, B any rhabdoid tumour, C
    # MPNST, D any solid tumour. A condition label is not an eligibility
    # criterion.
    age="All",
    match=[all_of(
        dx("Wilms' Tumor", "Rhabdoid Cancer", "Atypical Teratoid/Rhabdoid Tumor",
           "Malignant Peripheral Nerve Sheath Tumor"),
        age(">=1"),
        status("Recurrent", "Refractory"),
    )],
)

CURATIONS["NCT03067181"] = dict(
    # AGCT1531. Extracranial germ cell tumours. "There is no age limit for the
    # low risk stratum", so the trial carries no age bound even though two
    # strata do.
    age="All",
    match=[all_of(
        dx("Yolk Sac Tumor", "Embryonal Carcinoma", "Choriocarcinoma", "Seminoma",
           "Immature Teratoma", "Mixed Germ Cell Tumor",
           "Extra Gonadal Germ Cell Tumor"),
    )],
)


# --------------------------------------------------------------------- lymphoma
CURATIONS["NCT02393157"] = dict(
    # Obinutuzumab + ICE in relapsed/refractory CD20+ mature B-NHL. CD20 is a
    # surface marker read by flow cytometry, not a genomic criterion.
    age="Children",
    match=[all_of(
        dx("Diffuse Large B-Cell Lymphoma, NOS", "Burkitt Lymphoma",
           "High-Grade B-Cell Lymphoma, NOS",
           "Primary Mediastinal (Thymic) Large B-Cell Lymphoma",
           "B-Lymphoblastic Leukemia/Lymphoma, NOS", "Follicular Lymphoma"),
        age(">=3"), age("<=31"),
        status("Recurrent", "Refractory"),
    )],
)


# ------------------------------------------------------------- soft tissue (2)
CURATIONS["NCT05304585"] = dict(
    # ARST2032. The fusion requirement is negative and applies to one subtype
    # only: embryonal and spindle cell/sclerosing RMS enrol regardless, while
    # alveolar RMS must be "FOXO1 fusion negative".
    age="Children",
    match=[all_of(
        any_of(
            dx("Embryonal Rhabdomyosarcoma"),
            dx("Spindle Cell/Sclerosing Rhabdomyosarcoma"),
            all_of(dx("Alveolar Rhabdomyosarcoma"), fusion("FOXO1", negated=True)),
        ),
        age("<=21"),
    )],
)

CURATIONS["NCT06083883"] = dict(
    # NY-ESO-1 TCR-NK. NY-ESO-1 (CTAG1B) is scored by immunohistochemistry and
    # HLA-A*02 is the patient's germline type, not a tumour alteration. Neither
    # is a genomic match criterion.
    age="All",
    match=[all_of(
        dx("Synovial Sarcoma", "Myxoid/Round-Cell Liposarcoma"),
        age(">=16"), age("<=80"),
        status("Recurrent", "Refractory"),
    )],
)

CURATIONS["NCT06865664"] = dict(
    # FGFR4 CAR-T. The trial states the opposite of a biomarker requirement:
    # "Since FGFR4 expression is universal in rhabdomyosarcoma, confirmation of
    # FGFR4 expression is not required."
    age="Children",
    match=[all_of(
        dx("Rhabdomyosarcoma"),
        age(">=3"), age("<=39"),
        status("Recurrent", "Refractory"),
    )],
)


# ---------------------------------------------------------------- bone sarcoma
CURATIONS["NCT07297979"] = dict(
    # "Histologically or cytologically confirmed EWS with molecular evidence of
    # an EWSR1 translocation with an ETS family gene, eg, FLI1, ERG".
    age="All",
    match=[all_of(
        dx("Ewing Sarcoma"),
        fusion("EWSR1"),
        any_of(fusion("FLI1"), fusion("ERG")),
        age(">=2"),
        status("Recurrent", "Refractory"),
    )],
)

CURATIONS["NCT03900793"] = dict(
    age="All",
    match=[all_of(
        dx("Osteosarcoma"),
        age(">=10"),
        status("Recurrent", "Refractory"),
    )],
)


# ---------------------------------------------------------------- tumour-agnostic
CURATIONS["NCT04094610"] = dict(
    # Repotrectinib. Deliberately has no diagnosis criterion: any advanced
    # solid tumour, lymphoma or primary CNS tumour qualifies, and the
    # alteration alone decides eligibility. A key with diagnoses here would
    # reward inventing them.
    age="Children",
    match=[all_of(
        any_of(
            gene("ROS1", "Mutation"),
            fusion("ROS1"),
            gene("ROS1", "Copy Number Variation", cnv_call="High Amplification"),
            fusion("NTRK1"), fusion("NTRK2"), fusion("NTRK3"),
        ),
        age("<=25"),
    )],
)


# ---------------------------------------------------------------------- CNS (2)
CURATIONS["NCT05106296"] = dict(
    # Ibrutinib + indoximod. Histology only; nothing molecular is required.
    age="Children",
    match=[all_of(
        dx("Ependymoma", "Medulloblastoma", "Glioblastoma, IDH-Wildtype"),
        age(">=3"), age("<=25"),
        status("Recurrent", "Refractory"),
    )],
)

CURATIONS["NCT04655404"] = dict(
    # Larotrectinib. The fusion is required: tumours must "harbor an NTRK
    # fusion alteration by FISH, PCR, or next generation sequencing".
    age="Children",
    match=[all_of(
        dx("High-Grade Glioma, NOS", "Glioblastoma, IDH-Wildtype",
           "Diffuse Midline Glioma, H3 K27-Altered"),
        any_of(fusion("NTRK1"), fusion("NTRK2"), fusion("NTRK3")),
        age("<=21"),
    )],
)

CURATIONS["NCT04185038"] = dict(
    # B7-H3 CAR-T, locoregional. B7-H3 (CD276) is scored by IHC and is not
    # part of the inclusion criteria here in any case.
    age="Children",
    match=[all_of(
        dx("Diffuse Midline Glioma, H3 K27-Altered", "Ependymoma",
           "Medulloblastoma", "Germ Cell Tumor, Brain"),
        age(">=1"), age("<=26"),
        status("Recurrent", "Refractory"),
    )],
)


# -------------------------------------------------------------- pan-tumour (2)
CURATIONS["NCT02332668"] = dict(
    # KEYNOTE-051. Broad by design - "locally-advanced or metastatic solid
    # malignancy or lymphoma" - with melanoma and relapsed/refractory classical
    # Hodgkin lymphoma as the named cohorts. PD-L1 and MSI-high are IHC and a
    # mutational-signature phenotype, neither a hugo_symbol criterion.
    age="Children",
    match=[all_of(
        dx("Melanoma", "Classical Hodgkin Lymphoma"),
        age(">=0.5"), age("<18"),
    )],
)

CURATIONS["NCT07440290"] = dict(
    # DETERMINE arm 07. Tumour-agnostic on the alteration: "a malignancy
    # harbouring an oncogenic alteration in BRAF V600, including Langerhans
    # cell histiocytosis".
    age="All",
    match=[all_of(
        dx("Langerhans Cell Histiocytosis"),
        gene("BRAF", "Mutation"),
        age(">=1"),
    )],
)

CURATIONS["NCT04897321"] = dict(
    # B7-H3 CAR-T in paediatric solid tumours. B7-H3 positivity is required but
    # is an immunohistochemistry H-score, not a genomic alteration.
    age="Children",
    match=[all_of(
        dx("Osteosarcoma", "Rhabdomyosarcoma", "Neuroblastoma", "Ewing Sarcoma",
           "Wilms' Tumor", "Adrenocortical Carcinoma",
           "Desmoplastic Small-Round-Cell Tumor"),
        age("<=21"),
        status("Recurrent", "Refractory"),
    )],
)


# ---------------------------------------------------------------- neuroblastoma
CURATIONS["NCT05489887"] = dict(
    # Naxitamab. MYCN amplification is the first of three alternatives, and the
    # second is explicitly "without MYCN amplification". Alternative cohorts.
    age="Children",
    match=[all_of(
        any_of(
            all_of(dx("Neuroblastoma", "Ganglioneuroblastoma"), amplified("MYCN")),
            all_of(dx("Neuroblastoma", "Ganglioneuroblastoma"), age(">=1.5")),
        ),
        age(">=1"), age("<=21"),
    )],
)

CURATIONS["NCT06071897"] = dict(
    # Risk stratification is by GPOH-NB2004 and INSS stage 4; no molecular
    # criterion appears in the inclusion list at all.
    age="Children",
    match=[all_of(
        dx("Neuroblastoma", "Ganglioneuroblastoma"),
        age(">=1.5"), age("<=18"),
    )],
)


# ---------------------------------------------------------------- leukaemia (2)
CURATIONS["NCT05745714"] = dict(
    # HEM-iSMART-C. Required: "Patients whose tumor presents alterations in the
    # IL-7R and/or JAK-STAT signaling pathways". USP9X is named too but is not
    # in the Kispi gene list, so its fusion partner DDX3X carries it.
    age="Children",
    match=[all_of(
        dx("B-Lymphoblastic Leukemia/Lymphoma, NOS", "T-Lymphoblastic Leukemia/Lymphoma"),
        any_of(*([gene(g, "Mutation") for g in
                  ("CRLF2", "EPOR", "JAK1", "JAK2", "JAK3", "IL7R", "SH2B3",
                   "DDX3X", "STAT5B", "DNM2", "PTPN2")]
                 + [fusion("CRLF2"), fusion("EPOR"), fusion("JAK2"),
                    fusion("DDX3X"), fusion("P2RY8")])),
        age(">=1"), age("<21"),
        status("Recurrent", "Refractory"),
    )],
)

CURATIONS["NCT05658640"] = dict(
    # HEM-iSMART-D. Required: "Patients whose tumor present RAS pathway
    # activating mutations including but not limited to KRAS, NRAS, HRAS, FLT3,
    # PTPN11, MAP2K1 ... cCBL; NF1 del".
    age="Children",
    match=[all_of(
        dx("B-Lymphoblastic Leukemia/Lymphoma, NOS", "T-Lymphoblastic Leukemia/Lymphoma"),
        any_of(
            *[gene(g, "Mutation") for g in
              ("KRAS", "NRAS", "HRAS", "FLT3", "PTPN11", "MAP2K1", "CBL")],
            gene("NF1", "Copy Number Variation", cnv_call="Homozygous Deletion"),
        ),
        age(">=1"), age("<21"),
        status("Recurrent", "Refractory"),
    )],
)


# -------------------------------------------------------------------- liver (2)
CURATIONS["NCT04634357"] = dict(
    # ET140203 T cells. AFP > 100 ng/mL is a serum marker and HLA-A2 is the
    # patient's germline type; neither is a tumour genomic criterion.
    age="Children",
    match=[all_of(
        dx("Hepatoblastoma", "Hepatocellular Carcinoma"),
        age(">=1"), age("<=21"),
        status("Recurrent", "Refractory"),
    )],
)
