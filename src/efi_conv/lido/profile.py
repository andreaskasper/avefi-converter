"""Institution specific configuration for the generic LIDO mapping.

LIDO is a standard, but the vocabularies used inside it are not. A
profile carries everything that differs between data providers, so
that a new provider needs a profile rather than a new converter.

"""

from dataclasses import dataclass, field

#: The lido:type values that mark a classification as carrying the
#: colour, the format or the access status rather than a genre. LIDO
#: does not prescribe them, so a provider labelling its classifications
#: in German needs its own values here.
DEFAULT_CLASSIFICATION_TYPES = {
    "colour": ("colour", "farbe", "farbigkeit"),
    "format": ("format", "traegerformat", "trägerformat"),
    "access": ("access", "zugang", "zugangsstatus"),
}


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
    film_work_type_terms : frozenset
        Lower case objectWorkType terms denoting film. Records whose
        work type is not among them are skipped, because only holdings
        metadata about film is in scope, not accompanying material.
        An empty set disables the filter.
    map_decades : bool
        Map decade expressions such as "50er Jahre" to a closed
        interval. Off by default: the representation has to be agreed
        with the data provider first, so decades are reported as
        unconvertible until it is.
    work_key_fields : tuple
        Fields whose combination identifies a work, so that several
        copies of the same film share one WorkVariant instead of
        producing a duplicate work each. Set to an empty tuple to mint
        one work per record.
    production_event_terms : frozenset
        Lower case eventType terms denoting a production event.
    publication_event_terms : frozenset
        Lower case eventType terms denoting a publication event.
    director_role_terms : frozenset
        Lower case roleActor terms denoting a directing activity. Kept
        for profiles that only ever mapped the director; a term listed
        here means the same as mapping it to ``Director``.
    role_activity_map : dict
        Lower case roleActor term to the AVefi activity type it
        denotes, e.g. ``{"musik": "Composer"}``. The activity class
        follows from the type: the sixteen activity vocabularies of
        the schema share no value, so naming the role is enough and a
        profile does not have to know the class names.
    creation_event_terms : frozenset
        Lower case eventType terms denoting an act of creation whose
        actors belong to the production. Providers that model the
        people separately from the making of the copy put them in an
        event of their own; the activities are still production
        activities and are mapped onto the production event.
    duration_measurement_terms : frozenset
        Lower case measurementType terms denoting a running time.
    classification_types : dict
        AVefi target (``colour``, ``format`` or ``access``) to the
        lower case ``lido:type`` values marking a classification as
        carrying it. Classifications of any of these types are consumed
        by the vocabulary rules; the remaining ones become genres.
    colour_type_map : dict
        Source term (lower case) to AVefi ColourTypeEnum value.
    access_status_map : dict
        Source term (lower case) to AVefi ItemAccessStatusEnum value.
    format_map : dict
        Source term (lower case) to AVefi FormatFilmTypeEnum value.
    unknown_agent_names : frozenset
        Lower case placeholder names that do not denote an agent.
    avefi_handle_prefix : str or None
        Handle prefix under which AVefi identifiers are registered. A
        provider that has had identifiers minted for its holdings gets
        them back in its own system and exports them again, so a
        published identifier carrying this prefix is the copy's own
        AVefi identifier and is transferred as one. Set to None to
        ignore published identifiers.

    """

    issuer_info: dict
    description: str = "LIDO export"
    default_language: str | None = None
    film_work_type_terms: frozenset = frozenset(
        {
            "film",
            "filmwerk",
            "moving image",
            "bewegtbild",
            "video",
            "kinofilm",
            "dokumentarfilm",
            "spielfilm",
        }
    )
    map_decades: bool = False
    work_key_fields: tuple = ("primary_title", "director", "date")
    production_event_terms: frozenset = frozenset(
        {"production", "produktion", "herstellung"}
    )
    publication_event_terms: frozenset = frozenset(
        {"publication", "publikation", "veröffentlichung", "release"}
    )
    director_role_terms: frozenset = frozenset(
        {"regie", "director", "regisseur", "regisseurin"}
    )
    role_activity_map: dict = field(default_factory=dict)
    creation_event_terms: frozenset = frozenset(
        {
            "geistige schöpfung",
            "geistige schoepfung",
            "creation",
            "intellectual creation",
        }
    )
    duration_measurement_terms: frozenset = frozenset(
        {"laufzeit", "dauer", "spieldauer", "running time", "duration"}
    )
    classification_types: dict = field(
        default_factory=lambda: dict(DEFAULT_CLASSIFICATION_TYPES)
    )
    colour_type_map: dict = field(default_factory=dict)
    access_status_map: dict = field(default_factory=dict)
    format_map: dict = field(default_factory=dict)
    unknown_agent_names: frozenset = frozenset(
        {"unbekannt", "unknown", "verschiedene", "n.n.", "nn"}
    )
    avefi_handle_prefix: str | None = "21.11155"
