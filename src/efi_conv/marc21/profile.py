"""Institution specific configuration for the MARC21 mapping.

MARC21 is a standard, but MARC practice is not. Which field carries the
local identifier, which relator codes and terms an institution uses,
which genre vocabulary it cites in ``655 $2`` and which of the fixed
field codes it actually maintains differs from library to library and
from archive to archive. All of that lives here, so that a new data
provider needs a profile rather than a new converter.

The defaults describe common practice and are a starting point, not an
authority: a provider is expected to review them against its own
cataloguing rules.

"""

from dataclasses import dataclass, field

#: Bibliographic level (leader position 07) to AVefi work type.
BIBLIOGRAPHIC_LEVEL_MAP = {
    "a": "Analytic",
    "b": "Analytic",
    "c": "Collection",
    "d": "Analytic",
    "i": "Serial",
    "m": "Monographic",
    "s": "Serial",
}

#: Colour, field 007 position 03, for motion pictures and for
#: videorecordings alike.
COLOUR_TYPE_MAP = {
    "b": "BlackAndWhite",
    "c": "Colour",
    "m": "ColourBlackAndWhite",
}

#: Sound on medium or separate, field 007 position 05. The blank is
#: defined as "silent" at this position rather than as a fill.
SOUND_TYPE_MAP = {
    " ": "Silent",
    "a": "Sound",
    "b": "Sound",
}

#: Film gauge, field 007 position 07, motion pictures only. The 28 mm
#: and 8 mm variants MARC distinguishes but AVefi does not are left
#: unmapped deliberately and are reported when they occur.
FILM_GAUGE_MAP = {
    "a": "8mmFilm",
    "b": "Super8mmFilm",
    "c": "9.5mmFilm",
    "d": "16mmFilm",
    "f": "35mmFilm",
    "g": "70mmFilm",
}

#: Videorecording format, field 007 position 04, videorecordings only.
VIDEO_FORMAT_MAP = {
    "b": "VHS",
    "c": "UMatic",
    "e": "1InchCFormat",
    "f": "2InchQuadruplex",
    "j": "BetacamSP",
    "k": "SVHS",
}

#: Generation, field 007 position 11, motion pictures only.
GENERATION_ACCESS_MAP = {
    "e": "Master",
    "r": "Viewing",
}

#: Dimensions as spelled out in field 300 $c.
DIMENSION_FORMAT_MAP = {
    "8 mm": ("Film", "8mmFilm"),
    "9.5 mm": ("Film", "9.5mmFilm"),
    "16 mm": ("Film", "16mmFilm"),
    "17.5 mm": ("Film", "17.5mmFilm"),
    "35 mm": ("Film", "35mmFilm"),
    "70 mm": ("Film", "70mmFilm"),
    "super 8 mm": ("Film", "Super8mmFilm"),
    "super 16 mm": ("Film", "Super16mmFilm"),
}

#: Second indicator of field 246 to an AVefi title type. MARC
#: distinguishes nine kinds of varying title there; only the parallel
#: title of ind2=1, which is the title in another language, has an
#: AVefi counterpart. The others are reported and the title is kept as
#: an AlternativeTitle rather than dropped.
VARYING_TITLE_TYPE_MAP = {
    "1": "TranslatedTitle",
}

#: MARC relator codes and terms to an AVefi activity class and type.
#: Terms are matched in lower case, so that "Director" and "Regie" both
#: resolve. Anything absent from this table is reported rather than
#: guessed, because an agent filed under the wrong activity is worse
#: than an agent that is visibly missing.
RELATOR_ACTIVITIES = {
    # Relator codes, https://www.loc.gov/marc/relators/relacode.html
    "act": ("CastActivity", "CastMember"),
    "anm": ("AnimationActivity", "Animator"),
    "aus": ("WritingActivity", "Writer"),
    "cmp": ("MusicActivity", "Composer"),
    "cng": ("CinematographyActivity", "Cinematographer"),
    "cst": ("ProductionDesignActivity", "CostumeDesigner"),
    "dnc": ("CastActivity", "Dancer"),
    "drt": ("DirectingActivity", "Director"),
    "dst": ("CopyrightAndDistributionActivity", "Distributor"),
    "edm": ("EditingActivity", "FilmEditor"),
    "edt": ("WritingActivity", "Editor"),
    "fds": ("CopyrightAndDistributionActivity", "Distributor"),
    "flm": ("EditingActivity", "FilmEditor"),
    "fmk": ("DirectingActivity", "Filmmaker"),
    "fmp": ("ProducingActivity", "Producer"),
    "ivr": ("CastActivity", "Interviewer"),
    "lgd": ("CinematographyActivity", "GafferLighting"),
    "mus": ("MusicActivity", "MusicPerformer"),
    "nrt": ("CastActivity", "Narrator"),
    "pbl": ("ManifestationActivity", "Publisher"),
    "pmn": ("ProducingActivity", "ProductionManager"),
    "prf": ("CastActivity", "CastMember"),
    "prn": ("ProducingActivity", "ProductionCompany"),
    "pro": ("ProducingActivity", "Producer"),
    "sng": ("CastActivity", "Singer"),
    "snd": ("SoundActivity", "SoundDesigner"),
    "spn": ("ProducingActivity", "Sponsor"),
    "std": ("ProductionDesignActivity", "SetDesigner"),
    "vdg": ("CinematographyActivity", "Cinematographer"),
    # Relator terms, English and German
    "animation": ("AnimationActivity", "Animator"),
    "camera": ("CinematographyActivity", "Cinematographer"),
    "cast": ("CastActivity", "CastMember"),
    "cinematographer": ("CinematographyActivity", "Cinematographer"),
    "composer": ("MusicActivity", "Composer"),
    "darsteller": ("CastActivity", "CastMember"),
    "director": ("DirectingActivity", "Director"),
    "director of photography": (
        "CinematographyActivity",
        "Cinematographer",
    ),
    "distributor": ("CopyrightAndDistributionActivity", "Distributor"),
    "drehbuch": ("WritingActivity", "Writer"),
    "erzähler": ("CastActivity", "Narrator"),
    "film editor": ("EditingActivity", "FilmEditor"),
    "kamera": ("CinematographyActivity", "Cinematographer"),
    "montage": ("EditingActivity", "FilmEditor"),
    "musik": ("MusicActivity", "Composer"),
    "narrator": ("CastActivity", "Narrator"),
    "producer": ("ProducingActivity", "Producer"),
    "production company": ("ProducingActivity", "ProductionCompany"),
    "produktion": ("ProducingActivity", "Producer"),
    "produktionsfirma": ("ProducingActivity", "ProductionCompany"),
    "publisher": ("ManifestationActivity", "Publisher"),
    "regie": ("DirectingActivity", "Director"),
    "regisseur": ("DirectingActivity", "Director"),
    "regisseurin": ("DirectingActivity", "Director"),
    "schnitt": ("EditingActivity", "FilmEditor"),
    "screenwriter": ("WritingActivity", "Writer"),
    "ton": ("SoundActivity", "SoundEngineer"),
    "verleih": ("CopyrightAndDistributionActivity", "Distributor"),
    "writer": ("WritingActivity", "Writer"),
}


@dataclass(frozen=True)
class Marc21Profile:
    """Everything institution specific about a MARC21-XML export.

    Attributes
    ----------
    issuer_info : dict
        ``has_issuer_id`` and ``has_issuer_name`` for described_by.
    description : str
        Short description shown by ``efi-conv from --list-formats``.
    default_language : str or None
        ISO 639-2/B code assumed for the article handling of titles
        when field 008 states no language.
    identifier_fields : tuple
        Fields consulted for the local record identifier, in order.
        ``001`` is combined with the assigning agency in ``003``; for
        any other field the first ``$a`` is taken.
    agent_fields : tuple
        Fields carrying an agent together with a relator, in the order
        in which they are consulted.
    work_key_fields : tuple
        Fields whose combination identifies a work, so that several
        copies of one film share one WorkVariant. Set to an empty tuple
        to mint one work per record.
    moving_image_leader_types : frozenset
        Leader position 06 values that may denote a moving image.
    moving_image_categories : frozenset
        Field 007 position 00 values in scope, that is motion picture
        and videorecording.
    moving_image_carrier_types : frozenset
        RDA carrier type codes in 338 ``$b`` denoting a moving image.
        Consulted where the fixed fields do not decide: a record
        catalogued to RDA states the carrier there and may carry
        neither 007 nor a usable 008/33.
    moving_image_material_types : frozenset
        Field 008 position 33 values in scope, consulted when a record
        carries no 007.
    bibliographic_level_map : dict
        Leader position 07 to AVefi WorkVariantTypeEnum value.
    colour_type_map : dict
        Field 007 position 03 to AVefi ColourTypeEnum value.
    sound_type_map : dict
        Field 007 position 05 to AVefi SoundTypeEnum value.
    film_gauge_map : dict
        Field 007 position 07 to AVefi FormatFilmTypeEnum value,
        motion pictures only.
    video_format_map : dict
        Field 007 position 04 to AVefi FormatVideoTypeEnum value,
        videorecordings only.
    generation_access_map : dict
        Field 007 position 11 to AVefi ItemAccessStatusEnum value.
    dimension_format_map : dict
        Field 300 $c to a pair of AVefi format class and type.
    varying_title_type_map : dict
        Second indicator of field 246 to an AVefi TitleTypeEnum value.
        An indicator that is coded but not listed is reported and the
        title kept as an AlternativeTitle.
    relator_activities : dict
        Relator code or lower case relator term to a pair of AVefi
        activity class and type.
    genre_source_vocabularies : frozenset
        Values of ``655 $2`` accepted as a genre vocabulary. Empty
        means that every 655 is accepted, whatever its source.
    unknown_agent_names : frozenset
        Lower case placeholder names that do not denote an agent.
    map_decades : bool
        Passed through to the shared date normalisation.

    """

    issuer_info: dict
    description: str = "MARC21-XML export"
    default_language: str | None = None
    identifier_fields: tuple = ("001", "035")
    agent_fields: tuple = ("100", "110", "700", "710")
    work_key_fields: tuple = ("primary_title", "director", "date")
    moving_image_leader_types: frozenset = frozenset({"g"})
    moving_image_categories: frozenset = frozenset({"m", "v"})
    moving_image_material_types: frozenset = frozenset({"m", "v"})
    #: Film carriers mc mf mo mr mz, video carriers vc vd vf vr vz, and
    #: cr for an online resource — which says nothing on its own, but
    #: is only reached once the leader has called the record a
    #: projected medium.
    moving_image_carrier_types: frozenset = frozenset(
        {
            "mc",
            "mf",
            "mo",
            "mr",
            "mz",
            "vc",
            "vd",
            "vf",
            "vr",
            "vz",
            "cr",
        }
    )
    bibliographic_level_map: dict = field(
        default_factory=lambda: dict(BIBLIOGRAPHIC_LEVEL_MAP)
    )
    colour_type_map: dict = field(
        default_factory=lambda: dict(COLOUR_TYPE_MAP)
    )
    sound_type_map: dict = field(default_factory=lambda: dict(SOUND_TYPE_MAP))
    film_gauge_map: dict = field(default_factory=lambda: dict(FILM_GAUGE_MAP))
    video_format_map: dict = field(
        default_factory=lambda: dict(VIDEO_FORMAT_MAP)
    )
    generation_access_map: dict = field(
        default_factory=lambda: dict(GENERATION_ACCESS_MAP)
    )
    dimension_format_map: dict = field(
        default_factory=lambda: dict(DIMENSION_FORMAT_MAP)
    )
    varying_title_type_map: dict = field(
        default_factory=lambda: dict(VARYING_TITLE_TYPE_MAP)
    )
    relator_activities: dict = field(
        default_factory=lambda: dict(RELATOR_ACTIVITIES)
    )
    genre_source_vocabularies: frozenset = frozenset()
    unknown_agent_names: frozenset = frozenset(
        {"unbekannt", "unknown", "verschiedene", "n.n.", "nn", "anonymus"}
    )
    map_decades: bool = False
