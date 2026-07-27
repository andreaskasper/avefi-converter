"""Provider specific configuration for the Dublin Core converter.

Unqualified Dublin Core has fifteen flat, repeatable and untyped
elements. Whatever structure a record carries therefore lives in the
conventions of the data provider rather than in the schema, and those
conventions belong here rather than in the mapping.

The profile cannot repair what Dublin Core does not record. It can
only state the few things a provider is able to confirm about its own
export, so that the converter does not have to guess them.

"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DcProfile:
    """Everything provider specific about an oai_dc export.

    Attributes
    ----------
    issuer_info : dict
        ``has_issuer_id`` and ``has_issuer_name`` for described_by.
    description : str
        Short description shown by ``efi-conv from --list-formats``.
    default_language : str or None
        ISO 639-2/B code assumed when a title carries no xml:lang.
    film_type_terms : frozenset
        Lower case ``dc:type`` terms marking a record as film. Records
        of another type are skipped, because only holdings metadata
        about film is in scope, not accompanying material. An empty set
        disables the filter, which means every record of the export is
        taken to be a film.
    creator_is_director : bool
        The provider uses ``dc:creator`` for the director of the film.
        Off by default: Dublin Core does not say in what capacity a
        creator contributed, so creators are reported as unmapped
        until the provider has confirmed the convention.
    format_map : dict
        Source term (lower case) to AVefi FormatFilmTypeEnum value.
    language_usage : str
        AVefi LanguageUsageEnum value assumed for ``dc:language``.
        Dublin Core does not say whether a language is spoken, written
        as an intertitle or used for subtitles.
    map_decades : bool
        Map decade expressions such as "50er Jahre" to a closed
        interval. Off by default, as in the LIDO profile: the
        representation has to be agreed with the data provider first.

    """

    issuer_info: dict
    description: str = "Dublin Core (oai_dc) export"
    default_language: str | None = None
    film_type_terms: frozenset = frozenset(
        {
            "movingimage",
            "moving image",
            "http://purl.org/dc/dcmitype/movingimage",
            "info:eu-repo/semantics/movingimage",
            "film",
            "video",
        }
    )
    creator_is_director: bool = False
    format_map: dict = field(default_factory=dict)
    language_usage: str = "SpokenLanguage"
    map_decades: bool = False
