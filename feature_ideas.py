"""Ideas for OTHER important features that could be added to the invention, and how to include them."""
import re

from .features import tokenize
from .suggestions import DOMAIN_IDEAS, _hit

# (category, detection regex, how to include it, why it helps, effort)
CATALOG = [
    ("Security & privacy", r"secur|encrypt|privacy|authent|password|biometric|consent",
     "Encrypt data in transit and at rest, add sign-in with user roles, and keep only the minimum personal data.",
     "Builds user trust and helps meet data-protection rules.", "Medium"),
    ("Open API & integrations", r"\bapi\b|integrat|bluetooth|wi-?fi|mqtt|webhook|plugin|interoperab",
     "Expose a documented REST API / webhooks and support standard protocols so other tools can connect.",
     "Makes the product easy to adopt inside existing workflows.", "Medium"),
    ("Personalisation & learning", r"personal|adapt|learn|customi|tailor",
     "Let the system adjust thresholds and recommendations per user from their own history.",
     "Gives better results than a one-size-fits-all setting and can be a technical differentiator.", "Medium"),
    ("Analytics dashboard & reports", r"dashboard|analytic|report|visuali|insight|trend",
     "Add a dashboard with trends, comparisons and one-click exportable reports.",
     "Turns raw data into decisions users can act on.", "Low"),
    ("Smart alerts & automation", r"alert|notif|remind|automat|trigger|schedul",
     "Add rule-based or learned alerts (what happened, why, what to do) and optional automatic actions.",
     "Moves the product from passive display to active help.", "Low"),
    ("Offline / low-connectivity mode", r"offline|on-?device|edge|local processing|without internet",
     "Process and store data locally, then synchronise when a connection is available.",
     "Works where networks are poor and reduces latency and data cost.", "Medium"),
    ("Energy efficiency & sustainability", r"energy|battery|solar|low-?power|sustainab|recycl|eco",
     "Use duty-cycling or low-power modes, and consider recyclable or repairable materials / efficient algorithms.",
     "Lowers running cost and appeals to sustainability-focused buyers.", "Medium"),
    ("Safety, standards & compliance", r"safety|standard|certif|complian|regulat|fail-?safe|iso\b",
     "Identify the relevant standards for your field and add fail-safe behaviour and self-checks.",
     "Required for many markets and often a claimable technical feature.", "High"),
    ("Accessibility & ease of use", r"accessib|voice|multiling|language|inclusive|user-?friendly|ux",
     "Support voice or large-text modes, multiple languages and a simple first-use setup.",
     "Widens the user base, especially for non-technical users.", "Low"),
    ("Scalability & real-time performance", r"scal|distribut|real-?time|latency|throughput|cloud",
     "Design for many users or devices (queues, caching, horizontal scaling) and measure response time.",
     "Shows the idea works beyond a prototype.", "High"),
    ("Low cost & manufacturability", r"low-?cost|affordab|manufactur|modular|cheap",
     "Use common components, a modular design and a bill-of-materials estimate.",
     "Improves commercial viability and ease of production.", "Medium"),
    ("Evidence & validation", r"valid|accuracy|benchmark|clinical|pilot|evaluat|measured",
     "Plan a test with measurable results (accuracy, time saved, error rate) against a recognised reference.",
     "Evidence of improvement strengthens both the product and any patent argument.", "Medium"),
]


def generate(idea: str, features: list) -> list:
    text = (idea + " " + " ".join(features)).lower()
    out = []
    for cat, rx, how, why, effort in CATALOG:
        present = bool(re.search(rx, text))
        out.append({"category": cat, "status": "Already reflected in your idea" if present else "Can be added",
                    "how": how, "benefit": why, "effort": effort, "needs_verification": not present})
    toks = tokenize(idea)
    n = 0
    for keys, ideas in DOMAIN_IDEAS:
        if any(_hit(t, k) for t in toks for k in keys):
            for title, why in ideas:
                if n < 4:
                    out.append({"category": f"Domain idea: {title}", "status": "Can be added", "how": why,
                                "benefit": "Specific to the kind of invention you described.", "effort": "Medium",
                                "needs_verification": True})
                    n += 1
    out.sort(key=lambda x: x["status"] != "Can be added")      # suggestions first
    return out
