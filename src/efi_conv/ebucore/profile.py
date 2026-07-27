"""Configuration for the generic EBUCore mapping.

EBUCore (EBU Tech 3293) is a standard, so the traversal of a document
is the same for every data provider. What differs is the controlled
vocabulary a provider puts into the ``typeLabel`` attributes, and who
the issuer of the resulting AVefi records is. Both are carried by a
profile, so that a new provider needs a profile rather than a new
converter.

Unlike LIDO, EBUCore ships classification schemes of its own, and
providers do tend to use them. The defaults below therefore cover the
EBU schemes plus the English and German spellings met in practice; a
provider using a house vocabulary overrides the relevant map.

"""

from dataclasses import dataclass, field

#: Placeholder issuer shipped with the converter. EBUCore describes a
#: format, not an institution, so there is no ISIL to fill in here.
#: Replace it with the ISIL of the holding institution before the
#: records are used; the converter reports once per run that it is
#: still in place.
PLACEHOLDER_ISSUER_INFO = {
    "has_issuer_id": "https://w3id.org/avefi/issuer/unspecified",
    "has_issuer_name": "Unspecified data provider",
}

#: ``identifier/@typeLabel`` values denoting the identifier a record is
#: known by in the source system.
RECORD_IDENTIFIER_TYPE_LABELS = frozenset(
    {
        "main",
        "main identifier",
        "object identifier",
        "objectid",
        "primary",
        "record",
        "record id",
        "recordid",
        "local",
        "local identifier",
        "signatur",
        "shelfmark",
    }
)

#: ``title/@typeLabel`` values denoting the title a record is known by.
PRIMARY_TITLE_TYPE_LABELS = frozenset(
    {
        "main",
        "main title",
        "maintitle",
        "original",
        "original title",
        "originaltitle",
        "programme title",
        "series title",
        "title",
        "haupttitel",
        "originaltitel",
    }
)

#: ``alternativeTitle/@typeLabel`` values the mapping recognises. A
#: value outside this set is reported, and the title is still kept as
#: an AVefi AlternativeTitle so that nothing is lost.
ALTERNATIVE_TITLE_TYPE_LABELS = frozenset(
    {
        "alternative",
        "alternative title",
        "abbreviated",
        "distribution title",
        "episode title",
        "former",
        "translated",
        "translated title",
        "working",
        "working title",
        "arbeitstitel",
        "verleihtitel",
        "übersetzter titel",
    }
)

#: ``date/@typeLabel`` values denoting the production of the content,
#: in addition to the dedicated ``created`` and ``produced`` elements.
PRODUCTION_DATE_TYPE_LABELS = frozenset(
    {"production", "produced", "created", "produktion", "herstellung"}
)

#: ``date/@typeLabel`` values denoting publication, in addition to the
#: dedicated ``released`` and ``issued`` elements.
PUBLICATION_DATE_TYPE_LABELS = frozenset(
    {
        "publication",
        "published",
        "release",
        "released",
        "issued",
        "broadcast",
        "transmission",
        "erstausstrahlung",
        "veröffentlichung",
    }
)

#: ``role/@typeLabel`` values denoting a directing activity.
DIRECTOR_ROLE_LABELS = frozenset(
    {
        "director",
        "directing",
        "film director",
        "regie",
        "regisseur",
        "regisseurin",
    }
)

#: Placeholder names that do not denote an agent.
UNKNOWN_AGENT_NAMES = frozenset(
    {"unbekannt", "unknown", "n.n.", "nn", "diverse", "various"}
)

#: ``genre/@typeLabel`` values that AVefi records as a work form
#: rather than as a free text genre. Keys are lower case.
WORK_FORM_MAP = {
    "advertisement": "Commercial",
    "amateur film": "AmateurFilm",
    "commercial": "Commercial",
    "compilation": "Compilation",
    "documentary": "Documentary",
    "dokumentarfilm": "Documentary",
    "educational": "EducationalFilm",
    "experimental": "ExperimentalFilm",
    "feature": "Feature",
    "fiction": "Fiction",
    "home movie": "HomeMovie",
    "industrial film": "IndustrialFilm",
    "music video": "MusicVideo",
    "news": "Newsreel",
    "newsreel": "Newsreel",
    "series": "Series",
    "short": "Short",
    "spielfilm": "Fiction",
    "trailer": "Trailer",
    "werbefilm": "Commercial",
    "wochenschau": "Newsreel",
}

#: ``technicalAttributeString/@typeLabel`` values carrying the colour
#: system. EBUCore has no element for it, see ASSUMPTIONS.
COLOUR_ATTRIBUTE_LABELS = frozenset(
    {"colour", "color", "colour system", "colourtype", "farbe"}
)

#: Colour system term to AVefi ColourTypeEnum. Keys are lower case.
COLOUR_TYPE_MAP = {
    "b&w": "BlackAndWhite",
    "black and white": "BlackAndWhite",
    "bw": "BlackAndWhite",
    "colour": "Colour",
    "color": "Colour",
    "colour and black and white": "ColourBlackAndWhite",
    "farbe": "Colour",
    "schwarz-weiß": "BlackAndWhite",
    "schwarzweiß": "BlackAndWhite",
    "sepia": "Sepia",
    "sw": "BlackAndWhite",
    "tinted": "Tinted",
    "viragiert": "Tinted",
}

#: ``technicalAttributeString/@typeLabel`` values carrying the sound
#: system, used in addition to the presence of an ``audioFormat``.
SOUND_ATTRIBUTE_LABELS = frozenset({"sound", "sound system", "ton"})

#: Sound system term to AVefi SoundTypeEnum. Keys are lower case.
SOUND_TYPE_MAP = {
    "combined": "Combined",
    "mute": "Mute",
    "silent": "Silent",
    "sound": "Sound",
    "stumm": "Silent",
    "ton": "Sound",
}

#: ``format/medium/@typeLabel`` to an AVefi carrier format, given as
#: the name of the AVefi format class and the value of its type
#: enumeration. Keys are lower case.
MEDIUM_FORMAT_MAP = {
    "16mm": ("Film", "16mmFilm"),
    "16mm film": ("Film", "16mmFilm"),
    "35mm": ("Film", "35mmFilm"),
    "35mm film": ("Film", "35mmFilm"),
    "8mm": ("Film", "8mmFilm"),
    "super 8": ("Film", "Super8mmFilm"),
    "super8": ("Film", "Super8mmFilm"),
    "betacam sp": ("Video", "BetacamSP"),
    "digital betacam": ("Video", "DigitalBetacam"),
    "digibeta": ("Video", "DigitalBetacam"),
    "dvcpro": ("Video", "DVCPro"),
    "hdcam": ("Video", "HDCAM"),
    "u-matic": ("Video", "UMatic"),
    "vhs": ("Video", "VHS"),
    "blu-ray": ("Optical", "BluRay"),
    "dvd": ("Optical", "DVD"),
}

#: ``containerFormat`` name or ``containerEncoding/@typeLabel`` to an
#: AVefi digital file format. Keys are lower case.
CONTAINER_FORMAT_MAP = {
    "avi": "AVI",
    "dpx": "DPX",
    "dv": "DV",
    "mov": "MOV",
    "mp4": "MP4",
    "mpeg-4": "MP4",
    "mxf": "MXF",
    "quicktime": "MOV",
    "vob": "VOB",
    "webm": "WebM",
}

#: ``videoFormat/frameRate`` to AVefi FrameRateEnum. Keys are the
#: frame rate as written in the source.
FRAME_RATE_MAP = {
    "16": "16fps",
    "23.98": "23.98fps",
    "24": "24fps",
    "25": "25fps",
    "30": "30fps",
    "48": "48fps",
}

#: ``language/@typeLabel`` to AVefi LanguageUsageEnum. Keys are lower
#: case. EBUCore calls this the purpose of the language.
LANGUAGE_USAGE_MAP = {
    "audio description": "AudioDescription",
    "caption": "Captions",
    "captions": "Captions",
    "closed caption": "Captions",
    "dialogue": "SpokenLanguage",
    "dubbed": "Dubbed",
    "dubbed dialogue": "Dubbed",
    "intertitles": "Intertitles",
    "main original language": "SpokenLanguage",
    "no dialogue": "NoDialogue",
    "original": "SpokenLanguage",
    "original language": "SpokenLanguage",
    "sign language": "SignedLanguage",
    "spoken": "SpokenLanguage",
    "subtitles": "Subtitles",
    "sung": "SungLanguage",
    "titles": "Intertitles",
    "voice over": "VoiceOver",
    "untertitel": "Subtitles",
    "originalfassung": "SpokenLanguage",
}

#: ``publicationEvent/publicationMedium`` to AVefi
#: PublicationEventTypeEnum. Keys are lower case.
PUBLICATION_MEDIUM_EVENT_TYPE_MAP = {
    "cinema": "TheatricalDistributionEvent",
    "dvd": "HomeVideoPublicationEvent",
    "home video": "HomeVideoPublicationEvent",
    "internet": "OnlineTransmissionEvent",
    "online": "OnlineTransmissionEvent",
    "radio": "BroadcastEvent",
    "television": "BroadcastEvent",
    "tv": "BroadcastEvent",
    "web": "OnlineTransmissionEvent",
}


@dataclass(frozen=True)
class EbucoreProfile:
    """Everything provider specific about an EBUCore export.

    Attributes
    ----------
    issuer_info : dict
        ``has_issuer_id`` and ``has_issuer_name`` for described_by.
        Defaults to :data:`PLACEHOLDER_ISSUER_INFO`, which has to be
        replaced with the ISIL of the holding institution.
    description : str
        Short description shown by ``efi-conv from --list-formats``.
    default_language : str or None
        ISO 639-2/B code assumed when a title carries no xml:lang and
        the document does not declare one either.
    map_decades : bool
        Map decade expressions such as "50er Jahre" to a closed
        interval instead of reporting them as unconvertible.
    work_key_fields : tuple
        Fields whose combination identifies a work, so that several
        EBUCore records describing the same programme share one
        WorkVariant. Set to an empty tuple for one work per record.
    record_identifier_type_labels : frozenset
        Lower case ``identifier/@typeLabel`` values denoting the
        identifier the record is known by in the source system.
    primary_title_type_labels : frozenset
        Lower case ``title/@typeLabel`` values denoting the main title.
    alternative_title_type_labels : frozenset
        Lower case ``alternativeTitle/@typeLabel`` values the mapping
        recognises. Others are reported and kept as AlternativeTitle.
    production_date_type_labels : frozenset
        Lower case ``date/@typeLabel`` values denoting production.
    publication_date_type_labels : frozenset
        Lower case ``date/@typeLabel`` values denoting publication.
    director_role_labels : frozenset
        Lower case ``role/@typeLabel`` values denoting directing.
    unknown_agent_names : frozenset
        Lower case placeholder names that do not denote an agent.
    work_form_map : dict
        Genre term (lower case) to AVefi WorkFormEnum value. A genre
        term not listed here becomes a free text AVefi Genre.
    colour_attribute_labels : frozenset
        Lower case ``technicalAttributeString/@typeLabel`` values
        carrying the colour system.
    colour_type_map : dict
        Colour term (lower case) to AVefi ColourTypeEnum value.
    sound_attribute_labels : frozenset
        Lower case ``technicalAttributeString/@typeLabel`` values
        carrying the sound system.
    sound_type_map : dict
        Sound term (lower case) to AVefi SoundTypeEnum value.
    medium_format_map : dict
        ``format/medium/@typeLabel`` (lower case) to a pair of AVefi
        format class name and type enumeration value.
    container_format_map : dict
        Container format name (lower case) to AVefi
        FormatDigitalFileTypeEnum value.
    frame_rate_map : dict
        ``videoFormat/frameRate`` to AVefi FrameRateEnum value.
    language_usage_map : dict
        ``language/@typeLabel`` (lower case) to AVefi
        LanguageUsageEnum value.
    default_language_usage : str or None
        Usage assumed for a language without a purpose. None leaves
        the usage empty and reports the omission.
    publication_medium_event_type_map : dict
        ``publicationMedium`` (lower case) to AVefi
        PublicationEventTypeEnum value.
    default_publication_event_type : str
        Type used for a publication event whose medium is unknown.
        EBUCore is a broadcast schema, so BroadcastEvent is the
        default rather than ReleaseEvent.

    """

    issuer_info: dict = field(
        default_factory=lambda: dict(PLACEHOLDER_ISSUER_INFO)
    )
    description: str = "EBUCore export"
    default_language: str | None = None
    map_decades: bool = False
    work_key_fields: tuple = ("primary_title", "director", "date")
    record_identifier_type_labels: frozenset = RECORD_IDENTIFIER_TYPE_LABELS
    primary_title_type_labels: frozenset = PRIMARY_TITLE_TYPE_LABELS
    alternative_title_type_labels: frozenset = ALTERNATIVE_TITLE_TYPE_LABELS
    production_date_type_labels: frozenset = PRODUCTION_DATE_TYPE_LABELS
    publication_date_type_labels: frozenset = PUBLICATION_DATE_TYPE_LABELS
    director_role_labels: frozenset = DIRECTOR_ROLE_LABELS
    unknown_agent_names: frozenset = UNKNOWN_AGENT_NAMES
    work_form_map: dict = field(default_factory=lambda: dict(WORK_FORM_MAP))
    colour_attribute_labels: frozenset = COLOUR_ATTRIBUTE_LABELS
    colour_type_map: dict = field(
        default_factory=lambda: dict(COLOUR_TYPE_MAP)
    )
    sound_attribute_labels: frozenset = SOUND_ATTRIBUTE_LABELS
    sound_type_map: dict = field(default_factory=lambda: dict(SOUND_TYPE_MAP))
    medium_format_map: dict = field(
        default_factory=lambda: dict(MEDIUM_FORMAT_MAP)
    )
    container_format_map: dict = field(
        default_factory=lambda: dict(CONTAINER_FORMAT_MAP)
    )
    frame_rate_map: dict = field(default_factory=lambda: dict(FRAME_RATE_MAP))
    language_usage_map: dict = field(
        default_factory=lambda: dict(LANGUAGE_USAGE_MAP)
    )
    default_language_usage: str | None = "SpokenLanguage"
    publication_medium_event_type_map: dict = field(
        default_factory=lambda: dict(PUBLICATION_MEDIUM_EVENT_TYPE_MAP)
    )
    default_publication_event_type: str = "BroadcastEvent"

    def uses_placeholder_issuer(self) -> bool:
        """Return True if the issuer is still the shipped placeholder."""
        return (
            self.issuer_info.get("has_issuer_id")
            == PLACEHOLDER_ISSUER_INFO["has_issuer_id"]
        )
