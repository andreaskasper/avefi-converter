"""Configuration for the generic EN 15907 / EFG mapping.

The EFG schema is an implementation of the EN 15907 entity model, so
the traversal of a document is the same for every data provider. What
differs is the issuer and the vocabularies used inside the elements
that the schema declares as plain strings: title relations, agent
roles, carriers, colour and sound terms. All of that is carried by a
profile, so that a new data provider needs a profile rather than a new
converter.

"""

from dataclasses import dataclass, field

#: Issuer information shipped with the converter. An EFG export does
#: not carry an issuer in a form AVefi can use: ``item/provider`` names
#: the data provider in free text, not by ISIL. The placeholder makes
#: that visible instead of guessing an identifier, and the converter
#: reports its use once per input file. A real conversion supplies a
#: profile with the ISIL of the data provider.
PLACEHOLDER_ISSUER_INFO = {
    "has_issuer_id": "https://w3id.org/avefi/issuer/unspecified",
    "has_issuer_name": "Unspecified data provider",
}


def _preferred_title_relations() -> frozenset:
    return frozenset(
        {
            "",
            "main title",
            "original title",
            "originaltitle",
            "originaltitel",
            "preferred title",
            "title",
            "titel",
        }
    )


def _supplied_title_relations() -> frozenset:
    return frozenset({"devised title", "supplied title", "ermittelter titel"})


def _title_relation_map() -> dict:
    return {
        "abbreviated title": "AbbreviatedTitle",
        "acquisition title": "AcquisitionTitle",
        "alternative title": "AlternativeTitle",
        "alternativtitel": "AlternativeTitle",
        "archive title": "AcquisitionTitle",
        "corrected title": "CorrectedTitle",
        "other title": "AlternativeTitle",
        "pre-release title": "PreReleaseTitle",
        "prerelease title": "PreReleaseTitle",
        "search title": "SearchTitle",
        "series title": "SeriesTitle",
        "serientitel": "SeriesTitle",
        "translated title": "TranslatedTitle",
        "transliterated title": "TransliteratedTitle",
        "working title": "WorkingTitle",
        "arbeitstitel": "WorkingTitle",
    }


def _directing_role_map() -> dict:
    return {
        "assistant director": "AssistantDirector",
        "casting director": "CastingDirector",
        "creator": "Creator",
        "director": "Director",
        "filmmaker": "Filmmaker",
        "realisateur": "Director",
        "regie": "Director",
        "regieassistenz": "AssistantDirector",
        "regisseur": "Director",
        "regisseurin": "Director",
        "réalisateur": "Director",
        "second unit director": "SecondUnitDirector",
    }


def _production_event_type_map() -> dict:
    return {
        "casting": "CastingEvent",
        "indoor shooting": "IndoorShootingEvent",
        "outdoor shooting": "OutdoorShootingEvent",
        "post-production": "PostProductionEvent",
        "postproduction": "PostProductionEvent",
    }


def _publication_event_type_map() -> dict:
    return {
        "broadcast": "BroadcastEvent",
        "distribution": "DistributionEvent",
        "dvd release": "HomeVideoPublicationEvent",
        "erstaufführung": "ReleaseEvent",
        "home video": "HomeVideoPublicationEvent",
        "kinostart": "TheatricalDistributionEvent",
        "non-theatrical distribution": "NonTheatricalDistributionEvent",
        "online transmission": "OnlineTransmissionEvent",
        "premiere": "ReleaseEvent",
        "pre-release": "PreReleaseEvent",
        "release": "ReleaseEvent",
        "theatrical distribution": "TheatricalDistributionEvent",
        "theatrical release": "TheatricalDistributionEvent",
        "tv broadcast": "BroadcastEvent",
        "uraufführung": "ReleaseEvent",
    }


def _colour_type_map() -> dict:
    return {
        "b&w": "BlackAndWhite",
        "black & white": "BlackAndWhite",
        "black and white": "BlackAndWhite",
        "black and white/colour": "ColourBlackAndWhite",
        "bw": "BlackAndWhite",
        "color": "Colour",
        "colour": "Colour",
        "colour/black and white": "ColourBlackAndWhite",
        "farbe": "Colour",
        "schwarz-weiß": "BlackAndWhite",
        "schwarzweiß": "BlackAndWhite",
        "sepia": "Sepia",
        "sw": "BlackAndWhite",
        "tinted": "Tinted",
        "tinted and toned": "BlackAndWhiteTintedAndToned",
        "toned": "BlackAndWhiteToned",
        "viragiert": "Tinted",
    }


def _sound_type_map() -> dict:
    return {
        "combined": "Combined",
        "mixed sound": "MixedSound",
        "mute": "Mute",
        "silent": "Silent",
        "sound": "Sound",
        "stumm": "Silent",
        "ton": "Sound",
    }


def _film_format_map() -> dict:
    return {
        "16mm": "16mmFilm",
        "17,5mm": "17.5mmFilm",
        "17.5mm": "17.5mmFilm",
        "35mm": "35mmFilm",
        "70mm": "70mmFilm",
        "8mm": "8mmFilm",
        "9,5mm": "9.5mmFilm",
        "9.5mm": "9.5mmFilm",
        "super 16": "Super16mmFilm",
        "super 8": "Super8mmFilm",
        "super16": "Super16mmFilm",
        "super16mm": "Super16mmFilm",
        "super8": "Super8mmFilm",
        "super8mm": "Super8mmFilm",
    }


def _video_format_map() -> dict:
    return {
        "betacam sp": "BetacamSP",
        "digibeta": "DigitalBetacam",
        "digital betacam": "DigitalBetacam",
        "dv": "DV",
        "dvcam": "DVCAM",
        "hdcam": "HDCAM",
        "hdv": "HDV",
        "minidv": "MiniDV",
        "s-vhs": "SVHS",
        "svhs": "SVHS",
        "u-matic": "UMatic",
        "umatic": "UMatic",
        "vhs": "VHS",
    }


def _optical_format_map() -> dict:
    return {
        "blu ray": "BluRay",
        "blu-ray": "BluRay",
        "bluray": "BluRay",
        "cd": "CD",
        "dvd": "DVD",
        "laserdisc": "LaserDisc",
    }


def _carrier_class_map() -> dict:
    return {
        "audio": "Audio",
        "digital": "DigitalFile",
        "digital file": "DigitalFile",
        "digital film": "DigitalFile",
        "file": "DigitalFile",
        "film": "Film",
        "optical": "Optical",
        "optical disc": "Optical",
        "video": "Video",
        "videotape": "Video",
    }


def _digital_file_format_map() -> dict:
    return {
        "application/mxf": "MXF",
        "avi": "AVI",
        "dpx": "DPX",
        "mov": "MOV",
        "mp4": "MP4",
        "mxf": "MXF",
        "quicktime": "MOV",
        "video/mp4": "MP4",
        "video/quicktime": "MOV",
        "video/webm": "WebM",
        "video/x-msvideo": "AVI",
        "vob": "VOB",
        "webm": "WebM",
    }


def _digital_encoding_map() -> dict:
    return {
        "mpeg-4": "MPEG4",
        "mpeg4": "MPEG4",
        "quicktime": "Quicktime",
        "realvideo": "RealVideo",
        "svcd": "SVCD",
        "vcd": "VCD",
        "windows media": "WindowsMedia",
        "wmv": "WindowsMedia",
    }


def _frame_rate_map() -> dict:
    return {
        "16": "16fps",
        "23,98": "23.98fps",
        "23.98": "23.98fps",
        "24": "24fps",
        "25": "25fps",
        "30": "30fps",
        "48": "48fps",
        "variable": "VariableFrameRate",
    }


def _extent_unit_map() -> dict:
    return {
        "feet": "Feet",
        "foot": "Feet",
        "ft": "Feet",
        "gb": "GigaByte",
        "kb": "KiloByte",
        "m": "Metre",
        "mb": "MegaByte",
        "meter": "Metre",
        "meters": "Metre",
        "metre": "Metre",
        "metres": "Metre",
        "tb": "TeraByte",
    }


def _language_usage_map() -> dict:
    return {
        "audio description": "AudioDescription",
        "captions": "Captions",
        "closing credits": "ClosingCredits",
        "commentary": "VoiceOver",
        "dialogue": "SpokenLanguage",
        "dubbed": "Dubbed",
        "dubbing": "Dubbed",
        "intertitle": "Intertitles",
        "intertitles": "Intertitles",
        "no dialogue": "NoDialogue",
        "opening credits": "OpeningCredits",
        "original": "SpokenLanguage",
        "original version": "SpokenLanguage",
        "signed language": "SignedLanguage",
        "spoken": "SpokenLanguage",
        "spoken language": "SpokenLanguage",
        "subtitle": "Subtitles",
        "subtitles": "Subtitles",
        "sung": "SungLanguage",
        "synchronfassung": "Dubbed",
        "untertitel": "Subtitles",
        "voice over": "VoiceOver",
        "voiceover": "VoiceOver",
        "zwischentitel": "Intertitles",
    }


@dataclass(frozen=True)
class EfgProfile:
    """Everything data provider specific about an EFG export.

    Attributes
    ----------
    issuer_info : dict
        ``has_issuer_id`` and ``has_issuer_name`` for described_by.
        Defaults to :data:`PLACEHOLDER_ISSUER_INFO`, whose use the
        converter reports, because an EFG document does not carry an
        ISIL for the data provider.
    description : str
        Short description shown by ``efi-conv from --list-formats``.
    default_language : str or None
        ISO 639-2/B code assumed when a title carries no usable
        ``lang`` attribute.
    map_decades : bool
        Map decade expressions such as "50er Jahre" to a closed
        interval. Off by default, so that they are reported as
        unconvertible until a representation has been agreed.
    preferred_identifier_schemes : tuple
        Values of the ``scheme`` attribute, most preferred first, used
        when an element carries several identifiers.
    work_key_fields : tuple
        Fields whose combination identifies a work, so that several
        efgEntity elements describing one film share a WorkVariant.
        Known names are ``identifier``, ``title`` and
        ``production_year``.
    work_key_fallback_fields : tuple
        Fields used instead when every value for work_key_fields is
        empty, that is when the avcreation carries no identifier.
    preferred_title_relations : frozenset
        Lower case ``title/relation`` values denoting the title that
        becomes the primary title. The empty string covers a title
        element without a relation.
    supplied_title_relations : frozenset
        Lower case ``title/relation`` values denoting a title supplied
        by the cataloguer, which becomes SuppliedDevisedTitle.
    title_relation_map : dict
        Lower case ``title/relation`` value to AVefi TitleTypeEnum.
    directing_role_map : dict
        Lower case ``relPerson/type`` or ``relCorporate/type`` value to
        AVefi DirectingActivityTypeEnum. Roles outside this map are
        reported as unmapped rather than dropped silently.
    unknown_agent_names : frozenset
        Lower case placeholder names that do not denote an agent.
    production_event_type_map : dict
        Lower case ``productionEvent/type`` to ProductionEventTypeEnum.
    publication_event_type_map : dict
        Lower case ``publicationEvent/type`` to
        PublicationEventTypeEnum.
    default_publication_event_type : str
        PublicationEventTypeEnum value used when the source states no
        type or a type outside the map. AVefi requires the field.
    publisher_activity_type : str
        ManifestationActivityTypeEnum value for
        ``publicationEvent/publisher``.
    colour_type_map : dict
        Lower case ``format/colour`` value to ColourTypeEnum.
    sound_type_map : dict
        Lower case ``format/sound`` value to SoundTypeEnum.
    film_format_map, video_format_map, optical_format_map : dict
        Lower case ``format/carrier`` or ``format/gauge`` value to the
        matching AVefi format enumeration. The maps are tried in this
        order.
    carrier_class_map : dict
        Lower case carrier term to the name of an AVefi format class,
        used for terms naming the kind of carrier without a specific
        format, such as "film" or "video".
    digital_file_format_map : dict
        Lower case ``item/fileFormat`` or ``format/digital/container``
        value to FormatDigitalFileTypeEnum.
    digital_encoding_map : dict
        Lower case ``format/digital/coding`` value to
        FormatDigitalFileEncodingTypeEnum.
    frame_rate_map : dict
        Lower case ``duration/@frameRate`` value to FrameRateEnum.
    extent_unit_map : dict
        Lower case ``dimension/@unit`` value to UnitEnum.
    language_usage_map : dict
        Lower case ``language/@usage`` value to LanguageUsageEnum.
    genre_keyword_types : frozenset
        Lower case ``keywords/@type`` values whose terms become
        has_genre. The empty string covers keywords without a type.
    subject_keyword_types : frozenset
        Lower case ``keywords/@type`` values whose terms become
        has_subject.
    moving_image_item_types : frozenset
        Lower case ``item/type`` values denoting a moving image. Items
        of another type are still converted, but reported, because the
        AVefi model only describes moving image holdings.
    work_description_target : str
        Where ``avcreation/description`` and ``avcreation/note`` go.
        ``report`` states in the report that AVefi has no field for
        them at work level, ``manifestation_note`` writes them to
        has_note of every manifestation of the work.

    """

    issuer_info: dict = field(
        default_factory=lambda: dict(PLACEHOLDER_ISSUER_INFO)
    )
    description: str = "EN 15907 export in the EFG 3.2 schema"
    default_language: str | None = None
    map_decades: bool = False
    preferred_identifier_schemes: tuple = ()
    work_key_fields: tuple = ("identifier",)
    work_key_fallback_fields: tuple = ("title", "production_year")
    preferred_title_relations: frozenset = field(
        default_factory=_preferred_title_relations
    )
    supplied_title_relations: frozenset = field(
        default_factory=_supplied_title_relations
    )
    title_relation_map: dict = field(default_factory=_title_relation_map)
    directing_role_map: dict = field(default_factory=_directing_role_map)
    unknown_agent_names: frozenset = frozenset(
        {"anonymous", "n.n.", "nn", "unbekannt", "unknown", "verschiedene"}
    )
    production_event_type_map: dict = field(
        default_factory=_production_event_type_map
    )
    publication_event_type_map: dict = field(
        default_factory=_publication_event_type_map
    )
    default_publication_event_type: str = "UnknownEvent"
    publisher_activity_type: str = "Publisher"
    colour_type_map: dict = field(default_factory=_colour_type_map)
    sound_type_map: dict = field(default_factory=_sound_type_map)
    film_format_map: dict = field(default_factory=_film_format_map)
    video_format_map: dict = field(default_factory=_video_format_map)
    optical_format_map: dict = field(default_factory=_optical_format_map)
    carrier_class_map: dict = field(default_factory=_carrier_class_map)
    digital_file_format_map: dict = field(
        default_factory=_digital_file_format_map
    )
    digital_encoding_map: dict = field(default_factory=_digital_encoding_map)
    frame_rate_map: dict = field(default_factory=_frame_rate_map)
    extent_unit_map: dict = field(default_factory=_extent_unit_map)
    language_usage_map: dict = field(default_factory=_language_usage_map)
    genre_keyword_types: frozenset = frozenset(
        {"", "form", "gattung", "genre"}
    )
    subject_keyword_types: frozenset = frozenset(
        {"keyword", "schlagwort", "subject", "thema"}
    )
    moving_image_item_types: frozenset = frozenset(
        {"film", "moving image", "movingimage", "video"}
    )
    work_description_target: str = "report"

    def uses_placeholder_issuer(self) -> bool:
        """Return True if the profile still carries the placeholder."""
        return (
            self.issuer_info.get("has_issuer_id")
            == PLACEHOLDER_ISSUER_INFO["has_issuer_id"]
        )
