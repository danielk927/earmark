# Microsoft sponsor pack (Cal Hacks 13.0)

Compiled 2026-10-24 by a read-only research agent.
Anything not confirmed against an official page is marked UNVERIFIED.
Azure hosting commands live in `docs/sponsors/vendor-notes/azure.md`.

## 1. Source status

| Source | Status |
|---|---|
| Cal Hacks 13.0 Devpost, https://cal-hacks-13-0.devpost.com/ | Returned HTTP 403 to automated fetching; the prize text could not be read directly. |
| Cal Hacks site, https://www.calhacks.io/ | Lists Microsoft as a sponsor (logo links to microsoft.com); no challenge details on the page. |
| Sponsorship packet, https://hackberkeley.org/sponsorship.pdf | Confirms "October 23-25, 2026" at "Palace of Fine Arts \| San Francisco, CA", and that sponsors can "Host a tech prize (competition track)". |
| Microsoft challenge brief | Provided to the team by the organizers; reproduced in section 2 from `BUILD_BRIEF.md` 2.5. |
| "Customer Impact Award" | No public page found by web search. |

Search-engine snippets of the Devpost page (UNVERIFIED, truncated, not read from the page itself) describe the Microsoft grand prize as:
- a Microsoft Surface laptop for each member of the winning team;
- a chance to present remotely at a Microsoft "Delta/Frontier Co. FDE team" tech talk;
- 1:1 mentorship with senior FDEs.

**Human action:** open the Devpost page in a browser, copy the Microsoft prize text, and paste it below this line.
Also check whether either prize requires using a specific Microsoft service (for example Azure), because that is not stated in the brief.

## 2. Challenge brief (as given to the team)

Build a production-minded AI agent that solves a meaningful problem in finance, productivity, healthcare, or another high-impact domain.

Judges look for:
1. Customer understanding
2. Measurable usefulness
3. A path from prototype to production
4. Responsible design
5. End-to-end functionality

Prizes:
- **Grand Prize: Built for the Real World**
- **Microsoft Customer Impact Award**

## 3. Criterion to deliverable map for Earmark

Deliverables come from `BUILD_BRIEF.md` 6.1.
The "evidence" column is what a judge should be able to see or click in under a minute.

| Criterion | Deliverable | Evidence for judges |
|---|---|---|
| Customer understanding | `docs/project/CUSTOMER.md`: blind and low-vision users plus caregivers, the specific jobs Earmark does, why camera apps fall short | Named jobs-to-be-done, and any real conversation recorded with permission. Never invent interviews or quotes. |
| Measurable usefulness | Trial mode (5.I) with real results on the dashboard, plus live metrics | Guidance latency, time to find, medication adherence, shown as numbers on the deployed dashboard |
| Path from prototype to production | `docs/project/PRODUCTION.md`, plus a live Azure deployment | Public dashboard URL on Azure Static Web Apps and a memory agent running on Azure Container Apps; hardware cost per home; rollout plan |
| Responsible design | `docs/project/RESPONSIBLE_DESIGN.md` | Each design choice tied to a Microsoft Responsible AI principle and HAX guideline (section 4) |
| End-to-end functionality | `BUILD_BRIEF.md` section 8 definition of done, demonstrated live | One unbroken demo: object lifted, spoken guidance, remote label change, adherence update |

## 4. Responsible AI references for `docs/project/RESPONSIBLE_DESIGN.md`

### 4.1 Microsoft Responsible AI principles

Source: https://www.microsoft.com/en-us/ai/principles-and-approach

| Principle | Microsoft's one-line description |
|---|---|
| Fairness | "AI systems should treat all people fairly." |
| Reliability and safety | "AI systems should perform reliably and safely." |
| Privacy and security | "AI systems should be secure and respect privacy." |
| Inclusiveness | "AI systems should empower everyone and engage all people, regardless of their backgrounds." |
| Transparency | "AI systems should be understandable." |
| Accountability | "People should be accountable for AI systems." |

### 4.2 Primary documents to cite

| Document | URL | Source page |
|---|---|---|
| Microsoft Responsible AI Standard | https://go.microsoft.com/fwlink/?linkid=2272645 (also linked as https://go.microsoft.com/fwlink/?linkid=2311742 and https://aka.ms/RAI) | https://www.microsoft.com/en-us/ai/tools-practices and https://www.microsoft.com/en-us/ai/principles-and-approach |
| Responsible AI Standard reference guide | https://go.microsoft.com/fwlink/?linkid=2327425 | https://www.microsoft.com/en-us/ai/principles-and-approach |
| AI Impact Assessment Template | https://go.microsoft.com/fwlink/?linkid=2272455 | https://www.microsoft.com/en-us/ai/tools-practices |
| AI Impact Assessment Guide | https://go.microsoft.com/fwlink/?linkid=2272454 | https://www.microsoft.com/en-us/ai/tools-practices |
| Responsible AI Transparency Report 2026 | https://aka.ms/2026RAITransparencyReport | https://www.microsoft.com/en-us/ai/principles-and-approach |
| HAX Toolkit (Human-AI Experience) | https://www.microsoft.com/en-us/haxtoolkit/ | https://www.microsoft.com/en-us/haxtoolkit/ |
| Guidelines for Human-AI Interaction (CHI 2019 paper) | https://www.microsoft.com/en-us/research/publication/guidelines-for-human-ai-interaction/ | https://www.microsoft.com/en-us/research/project/guidelines-for-human-ai-interaction/ |
| Inclusive Design methodology | https://go.microsoft.com/fwlink/?linkid=2272852 | https://www.microsoft.com/en-us/ai/tools-practices |
| NIST AI Risk Management Framework | https://www.nist.gov/itl/ai-risk-management-framework | Referenced by https://learn.microsoft.com/en-us/azure/ai-foundry/responsible-ai/openai/overview |

### 4.3 Identify, Measure, Mitigate, Operate

Microsoft's responsible generative AI guidance is organized in four stages that follow the Responsible AI Standard.
Source: https://learn.microsoft.com/en-us/azure/ai-foundry/responsible-ai/openai/overview

1. **Identify:** "Identify and prioritize potential harms that could result from your AI system through iterative red-teaming, stress-testing, and analysis."
2. **Measure:** "Measure the frequency and severity of those harms by establishing clear metrics, creating measurement test sets, and completing iterative, systematic testing (both manual and automated)."
3. **Mitigate:** "Mitigate harms by implementing tools and strategies such as prompt engineering and using our Guardrails (previously content filters). Repeat measurement to test effectiveness after implementing mitigations."
4. **Operate:** "Define and execute a deployment and operational readiness plan."

The Operate stage lists a phased delivery plan, an incident response plan, a rollback plan, immediate action for unanticipated harms, effective user feedback channels, and telemetry.
These map directly onto `docs/project/PRODUCTION.md` sections.

A natural structure for `docs/project/RESPONSIBLE_DESIGN.md` is one table per stage: harms identified (wrong bottle named, stale location, overreliance), how each is measured (trial mode error rate, wrong-guidance count), the mitigation, and the operating plan.

### 4.4 HAX Guidelines for Human-AI Interaction, mapped to Earmark

The 18 guideline titles are from https://www.microsoft.com/en-us/haxtoolkit/library/.
The Earmark column is our suggestion, drawn from `BUILD_BRIEF.md` 6.1; it is not Microsoft text.

| # | Guideline | Earmark behavior that demonstrates it |
|---|---|---|
| G1 | Make clear what the system can do. | First-run voice intro: Earmark finds tagged items and never sees the room. |
| G2 | Make clear how well the system can do what it can do. | Honest uncertainty: says when it is not sure where something is. |
| G3 | Time services based on context. | Medication reminders only at dose times. |
| G4 | Show contextually relevant information. | Guidance names the spot and the nearest landmark. |
| G5 | Match relevant social norms. | Calm, short spoken phrasing. |
| G6 | Mitigate social biases. | Works by voice alone, with no reading or visual UI required. |
| G7 | Support efficient invocation. | One spoken request starts guidance. |
| G8 | Support efficient dismissal. | "Stop" ends guidance at once. |
| G9 | Support efficient correction. | The live wrong-jar correction; caregiver relabels from the dashboard in seconds. |
| G10 | Scope services when in doubt. | Never guesses which of two identical bottles is which; asks for a tag tap instead. |
| G11 | Make clear why the system did what it did. | "Last seen on the hall shelf at 9:14." |
| G12 | Remember recent interactions. | The memory agent answers "where did I put it last?" |
| G13 | Learn from user behavior. | Usual spots per object, if implemented. |
| G14 | Update and adapt cautiously. | Labels change only by explicit caregiver action. |
| G15 | Encourage granular feedback. | "That was wrong" is logged against the specific guidance event. |
| G16 | Convey the consequences of user actions. | Dashboard states that labeling photos are deleted after labeling. |
| G17 | Provide global controls. | Caregiver access controls and data deletion. |
| G18 | Notify users about changes. | Spoken notice when a caregiver relabels an item. |

The Azure guidance specifically calls out G2 ("Highlight potential inaccuracies") and G9 ("Review and edit interventions") as mitigations against overreliance.
Source: https://learn.microsoft.com/en-us/azure/ai-foundry/responsible-ai/openai/overview

### 4.5 Other Microsoft resources that fit Earmark

- **Presidio**, "Customizable de-identification for sensitive text and images", if any free text leaves the home: https://go.microsoft.com/fwlink/?linkid=2272459 (listed at https://www.microsoft.com/en-us/ai/tools-practices).
- **Microsoft Learn course**, "Embrace responsible AI principles and practices": https://go.microsoft.com/fwlink/?linkid=2320962 (listed at https://www.microsoft.com/en-us/ai/tools-practices).

## 5. Azure deployment for the "path to production" criterion

See `docs/sponsors/vendor-notes/azure.md`.
Summary:
- Dashboard on Azure Static Web Apps, Free plan, deployed from the CLI with a deployment token.
- Memory agent on Azure Container Apps with one pinned replica and secrets referenced by `secretref:`.
- Azure for Students gives $100 for 12 months with no credit card; ACR Tasks and region restrictions are the known blockers.

## 6. Open questions for the human

1. Paste the Microsoft prize text from Devpost into section 1 (the page blocks automated fetching).
2. Confirm the Azure for Students subscription is active, and list its allowed regions (Policy, then Assignments, then "Allowed resource deployment regions").
3. Confirm whether either Microsoft prize requires a specific Microsoft technology.
