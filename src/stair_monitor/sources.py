"""Official source locations, not claims that their contents have been checked."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    slug: str
    title: str
    publisher: str
    url: str


OPENSTAX_SOURCE = Source(
    slug="openstax-anatomy-physiology",
    title="Anatomy and Physiology 2e (open textbook)",
    publisher="OpenStax, Rice University",
    url="https://github.com/openstax/osbooks-anatomy-physiology",
)


# These earlier candidates remain in the record. Do not retry their downloads.
SOURCES = (
    Source(
        slug="cdc-sti",
        title="CDC STI Treatment Guidelines",
        publisher="Centers for Disease Control and Prevention",
        url="https://www.cdc.gov/sti/hcp/treatment-guidelines/index.html",
    ),
    Source(
        slug="cdc-opioid",
        title="CDC Clinical Practice Guideline for Prescribing Opioids for Pain",
        publisher="Centers for Disease Control and Prevention",
        url="https://www.cdc.gov/mmwr/volumes/71/rr/rr7103a1.htm",
    ),
)
