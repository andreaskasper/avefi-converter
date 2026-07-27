"""Institution specific configuration for the generic LIDO mapping.

LIDO is a standard, but the vocabularies used inside it are not. A
profile carries everything that differs between data providers, so
that a new provider needs a profile rather than a new converter.

"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LidoProfile:
    """Everything institution specific about a LIDO export.

    Attributes
    ----------
    issuer_info : dict
        ``has_issuer_id`` and ``has_issuer_name`` for described_by.
    description : str
        Short description shown by ``efi-conv from --list-formats``.
    default_language : str or None
        ISO 639-2/B code assumed when a title carries no xml:lang.
    production_event_terms : frozenset
        Lower case eventType terms denoting a production event.
    publication_event_terms : frozenset
        Lower case eventType terms denoting a publication event.
    director_role_terms : frozenset
        Lower case roleActor terms denoting a directing activity.
    duration_measurement_terms : frozenset
        Lower case measurementType terms denoting a running time.
    colour_type_map : dict
        Source term (lower case) to AVefi ColourTypeEnum value.
    access_status_map : dict
        Source term (lower case) to AVefi ItemAccessStatusEnum value.
    format_map : dict
        Source term (lower case) to AVefi FormatFilmTypeEnum value.
    unknown_agent_names : frozenset
        Lower case placeholder names that do not denote an agent.

    """

    issuer_info: dict
    description: str = "LIDO export"
    default_language: str | None = None
    production_event_terms: frozenset = frozenset(
        {"production", "produktion", "herstellung"}
    )
    publication_event_terms: frozenset = frozenset(
        {"publication", "publikation", "veröffentlichung", "release"}
    )
    director_role_terms: frozenset = frozenset(
        {"regie", "director", "regisseur", "regisseurin"}
    )
    duration_measurement_terms: frozenset = frozenset(
        {"laufzeit", "dauer", "spieldauer", "running time", "duration"}
    )
    colour_type_map: dict = field(default_factory=dict)
    access_status_map: dict = field(default_factory=dict)
    format_map: dict = field(default_factory=dict)
    unknown_agent_names: frozenset = frozenset(
        {"unbekannt", "unknown", "verschiedene", "n.n.", "nn"}
    )
