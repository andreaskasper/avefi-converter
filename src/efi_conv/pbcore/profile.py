"""Configuration for the generic PBCore mapping.

PBCore is a standard, so the traversal of a description document is
the same for every data provider. What differs is the vocabulary used
inside the elements: PBCore only recommends picklists, it does not
enforce them, and the ``@source`` attribute exists precisely so that a
provider can declare its own authority. Everything of that kind is
collected here, so that a new provider needs a profile rather than a
new converter.

Because PBCore is a format rather than an institution, the shipped
profile carries a placeholder issuer. It has to be replaced with the
ISIL of the holding institution before the records are used.

"""

from dataclasses import dataclass, field

#: Issuer used until the holding institution is known. PBCore does not
#: identify the data provider in a way that could be turned into an
#: ISIL, and guessing one would produce records that claim a provider
#: they do not come from.
PLACEHOLDER_ISSUER_ID = "https://w3id.org/avefi/issuer/unspecified"
PLACEHOLDER_ISSUER_NAME = "Unspecified data provider"
PLACEHOLDER_ISSUER_INFO = {
    "has_issuer_id": PLACEHOLDER_ISSUER_ID,
    "has_issuer_name": PLACEHOLDER_ISSUER_NAME,
}

#: pbcoreAssetType to WorkVariantTypeEnum. PBCore uses the asset type
#: for the structural level of the description, which is what
#: WorkVariant.type expresses as well.
DEFAULT_ASSET_TYPE_MAP = {
    "album": "Monographic",
    "clip": "Analytic",
    "collection": "Collection",
    "episode": "Analytic",
    "excerpt": "Analytic",
    "item": "Monographic",
    "program": "Monographic",
    "programme": "Monographic",
    "promo": "Monographic",
    "segment": "Analytic",
    "series": "Serial",
    "subseries": "Serial",
    "title": "Monographic",
    "trailer": "Monographic",
}

#: pbcoreTitle/@titleType to TitleTypeEnum.
DEFAULT_TITLE_TYPE_MAP = {
    "": "PreferredTitle",
    "abbreviated": "AbbreviatedTitle",
    "abbreviation": "AbbreviatedTitle",
    "alternate": "AlternativeTitle",
    "alternative": "AlternativeTitle",
    "distribution": "TitleProper",
    "episode": "TitleProper",
    "episode title": "TitleProper",
    "main": "PreferredTitle",
    "original": "PreferredTitle",
    "program": "PreferredTitle",
    "program title": "PreferredTitle",
    "segment": "TitleProper",
    "series": "SeriesTitle",
    "series title": "SeriesTitle",
    "supplied": "SuppliedDevisedTitle",
    "title": "PreferredTitle",
    "translated": "TranslatedTitle",
    "transliterated": "TransliteratedTitle",
    "working": "WorkingTitle",
}

#: creatorRole and contributorRole terms denoting a directing activity,
#: mapped to DirectingActivityTypeEnum. Every other role is reported as
#: unmapped rather than forced into one of these.
DEFAULT_DIRECTING_ROLE_MAP = {
    "assistant director": "AssistantDirector",
    "casting director": "CastingDirector",
    "co-director": "Director",
    "codirector": "Director",
    "continuity": "Continuity",
    "creator": "Creator",
    "directed by": "Director",
    "director": "Director",
    "filmmaker": "Filmmaker",
    "regie": "Director",
    "second unit director": "SecondUnitDirector",
}

#: publisherRole terms mapped to ManifestationActivityTypeEnum.
DEFAULT_PUBLISHER_ROLE_MAP = {
    "": "Publisher",
    "broadcaster": "Broadcaster",
    "distributor": "DistributorNonTheatrical",
    "publisher": "Publisher",
    "theatrical distributor": "DistributorTheatrical",
}

#: pbcoreAssetDate/@dateType of a publication date mapped to
#: PublicationEventTypeEnum.
DEFAULT_PUBLICATION_EVENT_TYPE_MAP = {
    "broadcast": "BroadcastEvent",
    "distributed": "DistributionEvent",
    "publication": "ReleaseEvent",
    "published": "ReleaseEvent",
    "release": "ReleaseEvent",
    "released": "ReleaseEvent",
}

#: pbcoreGenre terms that also determine WorkVariant.has_form.
DEFAULT_WORK_FORM_MAP = {
    "advertisement": "Commercial",
    "amateur film": "AmateurFilm",
    "commercial": "Commercial",
    "compilation": "Compilation",
    "documentary": "Documentary",
    "educational": "EducationalFilm",
    "experimental": "ExperimentalFilm",
    "feature": "Feature",
    "fiction": "Fiction",
    "home movie": "HomeMovie",
    "industrial": "IndustrialFilm",
    "music video": "MusicVideo",
    "news": "Newsreel",
    "newsreel": "Newsreel",
    "short": "Short",
    "trailer": "Trailer",
}

#: instantiationColors terms mapped to ColourTypeEnum.
DEFAULT_COLOUR_TYPE_MAP = {
    "b&w": "BlackAndWhite",
    "black and white": "BlackAndWhite",
    "black and white and color": "ColourBlackAndWhite",
    "black and white with color": "ColourBlackAndWhite",
    "bw": "BlackAndWhite",
    "color": "Colour",
    "color and black and white": "ColourBlackAndWhite",
    "colour": "Colour",
    "sepia": "Sepia",
    "tinted": "Tinted",
    "tinted and toned": "BlackAndWhiteTintedAndToned",
    "toned": "BlackAndWhiteToned",
}

#: instantiationPhysical terms mapped to the AVefi format class and the
#: value of its type enumeration.
DEFAULT_PHYSICAL_FORMAT_MAP = {
    "16mm film": ("Film", "16mmFilm"),
    "17.5mm film": ("Film", "17.5mmFilm"),
    "35mm film": ("Film", "35mmFilm"),
    "70mm film": ("Film", "70mmFilm"),
    "8mm film": ("Film", "8mmFilm"),
    "9.5mm film": ("Film", "9.5mmFilm"),
    "betacam sp": ("Video", "BetacamSP"),
    "blu-ray": ("Optical", "BluRay"),
    "cd": ("Optical", "CD"),
    "digital betacam": ("Video", "DigitalBetacam"),
    "dvcam": ("Video", "DVCAM"),
    "dvd": ("Optical", "DVD"),
    "hdcam": ("Video", "HDCAM"),
    "laserdisc": ("Optical", "LaserDisc"),
    "minidv": ("Video", "MiniDV"),
    "s-vhs": ("Video", "SVHS"),
    "super 16mm film": ("Film", "Super16mmFilm"),
    "super 8mm film": ("Film", "Super8mmFilm"),
    "u-matic": ("Video", "UMatic"),
    "vhs": ("Video", "VHS"),
}

#: instantiationDigital terms, both MIME types and bare file formats,
#: mapped to the AVefi format class and the value of its enumeration.
DEFAULT_DIGITAL_FORMAT_MAP = {
    "application/mxf": ("DigitalFile", "MXF"),
    "avi": ("DigitalFile", "AVI"),
    "dpx": ("DigitalFile", "DPX"),
    "dv": ("DigitalFile", "DV"),
    "image/x-dpx": ("DigitalFile", "DPX"),
    "mov": ("DigitalFile", "MOV"),
    "mp4": ("DigitalFile", "MP4"),
    "mxf": ("DigitalFile", "MXF"),
    "video/mp4": ("DigitalFile", "MP4"),
    "video/mxf": ("DigitalFile", "MXF"),
    "video/quicktime": ("DigitalFile", "MOV"),
    "video/webm": ("DigitalFile", "WebM"),
    "video/x-msvideo": ("DigitalFile", "AVI"),
    "vob": ("DigitalFile", "VOB"),
    "webm": ("DigitalFile", "WebM"),
}

#: instantiationGenerations terms mapped to ItemElementTypeEnum.
DEFAULT_ELEMENT_TYPE_MAP = {
    "moving image/duplicate negative": "DuplicateNegative",
    "moving image/duplicate positive": "DuplicatePositive",
    "moving image/negative": "ImageNegative",
    "moving image/original negative": "OriginalNegative",
    "moving image/positive": "Positive",
    "duplicate negative": "DuplicateNegative",
    "duplicate positive": "DuplicatePositive",
    "negative": "ImageNegative",
    "original negative": "OriginalNegative",
    "positive": "Positive",
}

#: instantiationGenerations and rightsSummary terms mapped to
#: ItemAccessStatusEnum.
DEFAULT_ACCESS_STATUS_MAP = {
    "moving image/copy: access": "Viewing",
    "moving image/copy: preservation": "Archive",
    "moving image/master": "Master",
    "access copy": "Viewing",
    "archive copy": "Archive",
    "distribution copy": "Distribution",
    "master": "Master",
    "preservation master": "Master",
    "viewing copy": "Viewing",
}

#: essenceTrackFrameRate values mapped to FrameRateEnum.
DEFAULT_FRAME_RATE_MAP = {
    "16": "16fps",
    "23.976": "23.98fps",
    "23.98": "23.98fps",
    "24": "24fps",
    "25": "25fps",
    "30": "30fps",
    "48": "48fps",
    "variable": "VariableFrameRate",
}

#: essenceTrackType mapped to the LanguageUsageEnum value describing
#: how the language of that track is used.
DEFAULT_TRACK_LANGUAGE_USAGE_MAP = {
    "audio": "SpokenLanguage",
    "caption": "Captions",
    "captions": "Captions",
    "subtitle": "Subtitles",
    "subtitles": "Subtitles",
    "text": "Subtitles",
}

#: unitsOfMeasure of instantiationDimensions and instantiationFileSize
#: mapped to UnitEnum.
DEFAULT_EXTENT_UNIT_MAP = {
    "feet": "Feet",
    "ft": "Feet",
    "gb": "GigaByte",
    "gigabytes": "GigaByte",
    "kb": "KiloByte",
    "kilobytes": "KiloByte",
    "m": "Metre",
    "mb": "MegaByte",
    "megabytes": "MegaByte",
    "meters": "Metre",
    "metres": "Metre",
    "tb": "TeraByte",
    "terabytes": "TeraByte",
}


@dataclass(frozen=True)
class PbcoreProfile:
    """Everything that differs between PBCore data providers.

    Attributes
    ----------
    issuer_info : dict
        ``has_issuer_id`` and ``has_issuer_name`` for described_by.
        Defaults to :data:`PLACEHOLDER_ISSUER_INFO`, which the
        converter reports once per run.
    description : str
        Short description shown by ``efi-conv from --list-formats``.
    default_language : str or None
        ISO 639-2/B code assumed when deriving an ordering name.
        PBCore has no language attribute on pbcoreTitle, so there is
        nothing to derive it from per title.
    default_language_usage : str
        LanguageUsageEnum value assumed for instantiationLanguage,
        which does not say how the language is used.
    map_decades : bool
        Map decade expressions to a closed interval instead of
        reporting them as unconvertible.
    work_key_fields : tuple
        Fields whose combination identifies a work, so that several
        assets describing the same film share one WorkVariant. Set to
        an empty tuple to mint one work per description document.
    authoritative_identifier_sources : tuple
        Lower case pbcoreIdentifier/@source values, most authoritative
        first. The first identifier matching one of them provides the
        source key; without a match the first identifier is used.
    asset_type_map : dict
        pbcoreAssetType (lower case) to WorkVariantTypeEnum value.
    default_work_type : str
        WorkVariantTypeEnum value for an asset without a type.
    title_type_map : dict
        titleType (lower case) to TitleTypeEnum value.
    primary_title_types : frozenset
        titleType values eligible for the primary title.
    production_date_types : frozenset
        pbcoreAssetDate/@dateType values denoting a production date.
    publication_date_types : frozenset
        pbcoreAssetDate/@dateType values denoting a publication date.
    manufacture_date_types : frozenset
        instantiationDate/@dateType values denoting the date the copy
        was made.
    directing_role_map : dict
        creatorRole or contributorRole to DirectingActivityTypeEnum.
    default_creator_activity : str or None
        DirectingActivityTypeEnum value for a pbcoreCreator without a
        creatorRole. None reports such a creator as unmapped instead.
    publisher_role_map : dict
        publisherRole to ManifestationActivityTypeEnum value.
    publication_event_type_map : dict
        pbcoreAssetDate/@dateType to PublicationEventTypeEnum value.
    default_publication_event_type : str
        PublicationEventTypeEnum value used when only a publisher is
        known, so that the record does not claim a release it does not
        state.
    corporate_agent_role_terms : frozenset
        Roles whose agent is a corporate body rather than a person.
    genre_subject_types : frozenset
        pbcoreSubject/@subjectType values whose subjects denote a genre
        and therefore go to has_genre instead of has_subject.
    work_form_map : dict
        pbcoreGenre term to WorkFormEnum value.
    part_of_relation_types : frozenset
        pbcoreRelationType values denoting containment in a larger
        work.
    moving_image_media_types : frozenset
        instantiationMediaType values in scope. PBCore is used for
        audio and text as well, and only moving image belongs in
        AVefi. An empty set disables the filter.
    colour_type_map : dict
        instantiationColors term to ColourTypeEnum value.
    physical_format_map : dict
        instantiationPhysical term to (format class, type value).
    digital_format_map : dict
        instantiationDigital term to (format class, type value).
    element_type_map : dict
        instantiationGenerations term to ItemElementTypeEnum value.
    access_status_map : dict
        instantiationGenerations or rightsSummary term to
        ItemAccessStatusEnum value.
    frame_rate_map : dict
        essenceTrackFrameRate value to FrameRateEnum value.
    audio_track_types : frozenset
        essenceTrackType values denoting an audio track, whose
        presence makes the item a sound copy.
    sound_type : str
        SoundTypeEnum value used when an audio track is present.
    track_language_usage_map : dict
        essenceTrackType to LanguageUsageEnum value.
    extent_unit_map : dict
        unitsOfMeasure to UnitEnum value.
    unknown_agent_names : frozenset
        Lower case placeholder names that do not denote an agent.

    """

    issuer_info: dict = field(
        default_factory=lambda: dict(PLACEHOLDER_ISSUER_INFO)
    )
    description: str = "PBCore 2.1 description document"
    default_language: str | None = None
    default_language_usage: str = "SpokenLanguage"
    map_decades: bool = False
    work_key_fields: tuple = ("primary_title", "director", "date")
    authoritative_identifier_sources: tuple = ()
    asset_type_map: dict = field(
        default_factory=lambda: dict(DEFAULT_ASSET_TYPE_MAP)
    )
    default_work_type: str = "Monographic"
    title_type_map: dict = field(
        default_factory=lambda: dict(DEFAULT_TITLE_TYPE_MAP)
    )
    primary_title_types: frozenset = frozenset(
        {"", "main", "original", "program", "program title", "title"}
    )
    production_date_types: frozenset = frozenset(
        {"", "created", "creation", "produced", "production"}
    )
    publication_date_types: frozenset = frozenset(
        {
            "broadcast",
            "distributed",
            "published",
            "publication",
            "release",
            "released",
        }
    )
    manufacture_date_types: frozenset = frozenset(
        {"", "created", "creation", "digitized", "manufactured"}
    )
    directing_role_map: dict = field(
        default_factory=lambda: dict(DEFAULT_DIRECTING_ROLE_MAP)
    )
    default_creator_activity: str | None = "Creator"
    publisher_role_map: dict = field(
        default_factory=lambda: dict(DEFAULT_PUBLISHER_ROLE_MAP)
    )
    publication_event_type_map: dict = field(
        default_factory=lambda: dict(DEFAULT_PUBLICATION_EVENT_TYPE_MAP)
    )
    default_publication_event_type: str = "UnknownEvent"
    corporate_agent_role_terms: frozenset = frozenset(
        {"broadcaster", "distributor", "production company", "publisher"}
    )
    genre_subject_types: frozenset = frozenset({"form", "genre"})
    work_form_map: dict = field(
        default_factory=lambda: dict(DEFAULT_WORK_FORM_MAP)
    )
    part_of_relation_types: frozenset = frozenset(
        {"is part of", "ispartof", "part of"}
    )
    moving_image_media_types: frozenset = frozenset(
        {"", "moving image", "movingimage", "video"}
    )
    colour_type_map: dict = field(
        default_factory=lambda: dict(DEFAULT_COLOUR_TYPE_MAP)
    )
    physical_format_map: dict = field(
        default_factory=lambda: dict(DEFAULT_PHYSICAL_FORMAT_MAP)
    )
    digital_format_map: dict = field(
        default_factory=lambda: dict(DEFAULT_DIGITAL_FORMAT_MAP)
    )
    element_type_map: dict = field(
        default_factory=lambda: dict(DEFAULT_ELEMENT_TYPE_MAP)
    )
    access_status_map: dict = field(
        default_factory=lambda: dict(DEFAULT_ACCESS_STATUS_MAP)
    )
    frame_rate_map: dict = field(
        default_factory=lambda: dict(DEFAULT_FRAME_RATE_MAP)
    )
    audio_track_types: frozenset = frozenset({"audio", "sound"})
    sound_type: str = "Sound"
    track_language_usage_map: dict = field(
        default_factory=lambda: dict(DEFAULT_TRACK_LANGUAGE_USAGE_MAP)
    )
    extent_unit_map: dict = field(
        default_factory=lambda: dict(DEFAULT_EXTENT_UNIT_MAP)
    )
    unknown_agent_names: frozenset = frozenset(
        {"n.n.", "nn", "unbekannt", "unknown", "various"}
    )
